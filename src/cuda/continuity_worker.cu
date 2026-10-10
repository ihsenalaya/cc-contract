// Inject by changing CUDA operations/pointers. Never emit a fault verdict.
#include <cuda_runtime.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

struct Packet { uint32_t id, generation, count, payload[16]; };
struct Observation { Packet consumed; uint32_t sum; };
static_assert(sizeof(Packet) == 19 * sizeof(uint32_t));
static_assert(sizeof(Observation) == 20 * sizeof(uint32_t));

__global__ void consume(const Packet *input, Observation *output) {
    // One instrumented consumer uses the same loaded words for its computation
    // and its observation; neither its input nor its output includes a fault id.
    Packet value = *input;
    uint32_t total = 0;
    for (int i = 0; i < 16; ++i) total += value.payload[i];
    output->consumed = value;
    output->sum = total;
}

void check(cudaError_t error) {
    if (error != cudaSuccess) throw error;
}

int main(int argc, char **argv) {
    if (argc != 3 || (std::strcmp(argv[2], "0") && std::strcmp(argv[2], "1"))) return 2;
    const std::string fault = argv[1];
    if (fault != "L1" && fault != "L2" && fault != "C1" && fault != "C2") return 2;
    const bool active = std::strcmp(argv[2], "1") == 0;
    Packet host[3];
    if (std::fread(host, sizeof(host), 1, stdin) != 1 || std::fgetc(stdin) != EOF) return 2;
    for (auto &packet : host) if (packet.count != 16) return 2;
    try {
        int devices = 0;
        cudaError_t status = cudaGetDeviceCount(&devices);
        if (status == cudaErrorNoDevice || status == cudaErrorInsufficientDriver ||
            (status == cudaSuccess && devices == 0)) {
            std::cout << "{\"backend\":\"cuda\",\"execution_status\":\"UNSUPPORTED\"}\n";
            return 0;
        }
        check(status);
        cudaStream_t producer, consumer;
        cudaEvent_t e1, e2;
        check(cudaStreamCreateWithFlags(&producer, cudaStreamNonBlocking));
        check(cudaStreamCreateWithFlags(&consumer, cudaStreamNonBlocking));
        check(cudaEventCreateWithFlags(&e1, cudaEventDisableTiming));
        check(cudaEventCreateWithFlags(&e2, cudaEventDisableTiming));
        Packet *a, *snapshot, *b, *pinned;
        Observation *out, observed{};
        check(cudaMalloc(&a, sizeof(Packet)));
        check(cudaMalloc(&snapshot, sizeof(Packet)));
        check(cudaMalloc(&b, sizeof(Packet)));
        check(cudaMalloc(&out, sizeof(Observation)));
        check(cudaMallocHost(&pinned, sizeof(host)));
        std::memcpy(pinned, host, sizeof(host));
        check(cudaMemcpyAsync(a, pinned, sizeof(Packet), cudaMemcpyHostToDevice, producer));
        check(cudaEventRecord(e1, producer));
        check(cudaStreamSynchronize(producer));
        cudaGraph_t graph = nullptr;
        cudaGraphExec_t executable = nullptr;
        const Packet *selected = a;
        if (fault == "L2") {
            check(cudaStreamBeginCapture(consumer, cudaStreamCaptureModeThreadLocal));
            consume<<<1, 1, 0, consumer>>>(a, out);
            check(cudaGetLastError());
            check(cudaStreamEndCapture(consumer, &graph));
            check(cudaGraphInstantiate(&executable, graph, nullptr, nullptr, 0));
            check(cudaMemcpyAsync(snapshot, pinned + 1, sizeof(Packet), cudaMemcpyHostToDevice, producer));
            check(cudaEventRecord(e2, producer));
            check(cudaStreamWaitEvent(consumer, e2, 0));
            if (!active) {
                size_t count = 1;
                cudaGraphNode_t node;
                check(cudaGraphGetNodes(graph, &node, &count));
                if (count != 1) throw std::runtime_error("unexpected graph");
                cudaKernelNodeParams params{};
                check(cudaGraphKernelNodeGetParams(node, &params));
                void *arguments[] = {&snapshot, &out};
                params.kernelParams = arguments;
                check(cudaGraphExecKernelNodeSetParams(executable, node, &params));
            }
            check(cudaGraphLaunch(executable, consumer));
        } else {
            if (!(active && (fault == "L1" || fault == "C1"))) {
                check(cudaMemcpyAsync(a, pinned + 1, sizeof(Packet), cudaMemcpyHostToDevice, producer));
                check(cudaEventRecord(e2, producer));
                check(cudaStreamWaitEvent(consumer, e2, 0));
            } else {
                check(cudaStreamWaitEvent(consumer, e1, 0));
            }
            if (fault == "C2") {
                check(cudaMemcpyAsync(b, pinned + 2, sizeof(Packet), cudaMemcpyHostToDevice, producer));
                check(cudaStreamSynchronize(producer));
                if (active) selected = b;
            }
            consume<<<1, 1, 0, consumer>>>(selected, out);
            check(cudaGetLastError());
        }
        check(cudaStreamSynchronize(consumer));
        check(cudaMemcpy(&observed, out, sizeof(observed), cudaMemcpyDeviceToHost));
        // Force the adverse L1 schedule without any simultaneous write/read.
        if (fault == "L1" && active) {
            check(cudaMemcpyAsync(a, pinned + 1, sizeof(Packet), cudaMemcpyHostToDevice, producer));
            check(cudaEventRecord(e2, producer));
        }
        check(cudaStreamSynchronize(producer));
        if (executable) check(cudaGraphExecDestroy(executable));
        if (graph) check(cudaGraphDestroy(graph));
        check(cudaFree(a)); check(cudaFree(snapshot)); check(cudaFree(b)); check(cudaFree(out));
        check(cudaFreeHost(pinned));
        check(cudaEventDestroy(e1)); check(cudaEventDestroy(e2));
        check(cudaStreamDestroy(producer)); check(cudaStreamDestroy(consumer));
        // Explicit fields avoid C++ aliasing and JSON-library dependencies.
        std::cout << "{\"backend\":\"cuda\",\"execution_status\":\"CUDA_SUCCESS\",\"consumed_words\":["
                  << observed.consumed.id << ',' << observed.consumed.generation << ',' << observed.consumed.count;
        for (uint32_t word : observed.consumed.payload) std::cout << ',' << word;
        std::cout << "],\"consumer_sum\":" << observed.sum << "}\n";
    } catch (cudaError_t error) {
        std::cout << "{\"backend\":\"cuda\",\"execution_status\":\"CUDA_ERROR\",\"cuda_code\":"
                  << static_cast<int>(error) << "}\n";
    } catch (...) {
        std::cout << "{\"backend\":\"cuda\",\"execution_status\":\"INFRA_FAILURE\"}\n";
    }
    return 0;
}
