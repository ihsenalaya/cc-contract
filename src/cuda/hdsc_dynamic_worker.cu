// Interactive bounded workload: next request is supplied after current output.
// No complete trace or detector is present in this process.
#include <cuda_runtime.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <stdexcept>

struct Packet { uint32_t id, generation, count, payload[16]; };
struct Result { Packet packet; uint32_t value, consumer; };
struct Request { uint32_t fault, active, kernel, reserved; Packet packets[3]; };
static_assert(sizeof(Request) == 4 * 4 + 3 * 19 * 4);

template <unsigned Consumer>
__global__ void consume(const Packet *input, Result *out) {
    Packet p = *input;
    uint32_t value = 0;
    for (unsigned i = 0; i < 16; ++i) {
        if (Consumer == 1) value += p.payload[i];
        else value ^= p.payload[i];
    }
    out->packet = p; out->value = value; out->consumer = Consumer;
}

void check(cudaError_t e) { if (e != cudaSuccess) throw e; }

int main() {
    try {
        int count = 0;
        auto status = cudaGetDeviceCount(&count);
        if (status == cudaErrorNoDevice || status == cudaErrorInsufficientDriver ||
            (status == cudaSuccess && count == 0)) {
            std::cout << "{\"execution_status\":\"UNSUPPORTED\"}" << std::endl; return 0;
        }
        check(status);
        cudaStream_t producer, consumer;
        cudaEvent_t old_ready, new_ready;
        check(cudaStreamCreateWithFlags(&producer, cudaStreamNonBlocking));
        check(cudaStreamCreateWithFlags(&consumer, cudaStreamNonBlocking));
        check(cudaEventCreateWithFlags(&old_ready, cudaEventDisableTiming));
        check(cudaEventCreateWithFlags(&new_ready, cudaEventDisableTiming));
        Packet *slots[3], *pinned;
        Result *result, *host;
        for (auto &slot : slots) check(cudaMalloc(&slot, sizeof(Packet)));
        check(cudaMallocHost(&pinned, 3 * sizeof(Packet)));
        check(cudaMallocHost(&host, sizeof(Result)));
        check(cudaMalloc(&result, sizeof(Result)));
        Request request;
        unsigned completed = 0;
        std::cout << "{\"ready\":true}" << std::endl;
        while (std::fread(&request, sizeof(request), 1, stdin) == 1) {
            if (++completed > 16 || request.fault > 3 || request.active > 1 || request.kernel > 1 || request.reserved > 1)
                throw std::runtime_error("invalid command");
            for (auto &p : request.packets) if (p.count != 16) throw std::runtime_error("bad packet");
            std::memcpy(pinned, request.packets, 3 * sizeof(Packet));
            cudaStream_t transfer_stream = request.reserved ? consumer : producer;
            // Reuse physical allocations only after the preceding consumer completed.
            check(cudaMemcpyAsync(slots[0], pinned, sizeof(Packet), cudaMemcpyHostToDevice, transfer_stream));
            check(cudaMemcpyAsync(slots[2], pinned + 2, sizeof(Packet), cudaMemcpyHostToDevice, transfer_stream));
            check(cudaEventRecord(old_ready, transfer_stream));
            check(cudaStreamSynchronize(transfer_stream));
            unsigned selected = 0, waited_epoch = 0, selected_packet = 0;
            cudaGraph_t graph = nullptr;
            cudaGraphExec_t exec = nullptr;
            auto launch = [&](const Packet *p) {
                if (request.kernel == 0) consume<1><<<1,1,0,consumer>>>(p, result);
                else consume<2><<<1,1,0,consumer>>>(p, result);
                check(cudaGetLastError());
            };
            if (request.fault == 1) {
                check(cudaStreamBeginCapture(consumer, cudaStreamCaptureModeThreadLocal));
                launch(slots[0]);
                check(cudaStreamEndCapture(consumer, &graph));
                check(cudaGraphInstantiate(&exec, graph, nullptr, nullptr, 0));
                check(cudaMemcpyAsync(slots[1], pinned + 1, sizeof(Packet), cudaMemcpyHostToDevice, transfer_stream));
                check(cudaEventRecord(new_ready, transfer_stream));
                check(cudaStreamWaitEvent(consumer, new_ready, 0)); waited_epoch = 1;
                if (!request.active) {
                    size_t n = 1; cudaGraphNode_t node;
                    check(cudaGraphGetNodes(graph, &node, &n));
                    if (n != 1) throw std::runtime_error("bad graph");
                    cudaKernelNodeParams params{};
                    check(cudaGraphKernelNodeGetParams(node, &params));
                    void *arguments[] = {&slots[1], &result}; params.kernelParams = arguments;
                    check(cudaGraphExecKernelNodeSetParams(exec, node, &params));
                    selected = 1; selected_packet = 1;
                }
                check(cudaGraphLaunch(exec, consumer));
            } else {
                if (!(request.active && (request.fault == 0 || request.fault == 2))) {
                    check(cudaMemcpyAsync(slots[0], pinned + 1, sizeof(Packet), cudaMemcpyHostToDevice, transfer_stream));
                    check(cudaEventRecord(new_ready, transfer_stream));
                    check(cudaStreamWaitEvent(consumer, new_ready, 0)); waited_epoch = 1; selected_packet = 1;
                } else {
                    check(cudaStreamWaitEvent(consumer, old_ready, 0));
                }
                if (request.active && request.fault == 3) { selected = 2; selected_packet = 2; }
                launch(slots[selected]);
            }
            check(cudaMemcpyAsync(host, result, sizeof(Result), cudaMemcpyDeviceToHost, consumer));
            check(cudaStreamSynchronize(consumer));
            if (request.fault == 0 && request.active) {
                check(cudaMemcpyAsync(slots[0], pinned + 1, sizeof(Packet), cudaMemcpyHostToDevice, transfer_stream));
                check(cudaEventRecord(new_ready, transfer_stream));
            }
            check(cudaStreamSynchronize(transfer_stream));
            if (exec) check(cudaGraphExecDestroy(exec));
            if (graph) check(cudaGraphDestroy(graph));
            std::cout << "{\"execution_status\":\"CUDA_SUCCESS\",\"consumed_words\":["
                      << host->packet.id << ',' << host->packet.generation << ',' << host->packet.count;
            for (auto word : host->packet.payload) std::cout << ',' << word;
            std::cout << "],\"value\":" << host->value << ",\"consumer\":" << host->consumer
                      << ",\"selected_slot\":" << selected << ",\"selected_packet\":" << selected_packet
                      << ",\"waited_epoch\":" << waited_epoch << "}" << std::endl;
        }
        if (!std::feof(stdin)) throw std::runtime_error("invalid input");
        for (auto slot : slots) check(cudaFree(slot));
        check(cudaFree(result)); check(cudaFreeHost(pinned)); check(cudaFreeHost(host));
        check(cudaEventDestroy(old_ready)); check(cudaEventDestroy(new_ready));
        check(cudaStreamDestroy(producer)); check(cudaStreamDestroy(consumer));
    } catch (cudaError_t e) {
        std::cout << "{\"execution_status\":\"CUDA_ERROR\",\"code\":" << int(e) << "}" << std::endl;
        return 3;
    } catch (...) {
        std::cout << "{\"execution_status\":\"INFRA_FAILURE\"}" << std::endl; return 4;
    }
}
