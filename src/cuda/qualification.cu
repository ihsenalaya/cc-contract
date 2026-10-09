// Bounded legal CUDA qualification. Never changes CC, driver, MIG or device state.
#include <cuda_runtime.h>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void checked(cudaError_t status, const char* operation) {
  if (status != cudaSuccess) throw std::runtime_error(std::string(operation) + ": " + cudaGetErrorString(status));
}
static int pattern(int index, int generation) {
  return index == 0 ? generation : ((index * 17 + generation * 31) % 8191) - 4095;
}
static void array_json(const int* p, int size) {
  std::cout << '[';
  for (int i = 0; i < size; ++i) { if (i) std::cout << ','; std::cout << p[i]; }
  std::cout << ']';
}
__global__ void affine(const int* in, int* out, int size) {
  const int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < size) out[i] = i == 0 ? in[i] : 2 * in[i] + 1;
}
static bool sequence(int size, int generation, const std::string& family, bool kernel, int repeat) {
  const size_t bytes = static_cast<size_t>(size) * sizeof(int);
  int *host = nullptr, *observed = nullptr, *device = nullptr, *result = nullptr;
  cudaStream_t upload, download;
  cudaEvent_t ready;
  checked(cudaMallocHost(&host, bytes), "allocate pinned input");
  checked(cudaMallocHost(&observed, bytes), "allocate pinned output");
  checked(cudaMalloc(&device, bytes), "allocate device input");
  checked(cudaMalloc(&result, bytes), "allocate device output");
  checked(cudaStreamCreateWithFlags(&upload, cudaStreamNonBlocking), "create upload stream");
  checked(cudaStreamCreateWithFlags(&download, cudaStreamNonBlocking), "create download stream");
  checked(cudaEventCreateWithFlags(&ready, cudaEventDisableTiming), "create completion event");
  bool pass = true;
  // Reuse is explicit: do not modify any host/device buffer before completion.
  for (int round = 0; round < (family == "T02" || family == "T05" ? 3 : 1); ++round) {
    int gen = generation + round;
    std::vector<int> expected(size);
    for (int i = 0; i < size; ++i) {
      host[i] = pattern(i, gen);
      expected[i] = kernel && i != 0 ? 2 * host[i] + 1 : host[i];
    }
    const auto start = std::chrono::steady_clock::now();
    checked(cudaMemcpyAsync(device, host, bytes, cudaMemcpyHostToDevice, upload), "H2D copy");
    if (kernel) {
      affine<<<(size + 255) / 256, 256, 0, upload>>>(device, result, size);
      checked(cudaGetLastError(), "affine kernel launch");
    }
    cudaStream_t sink = upload;
    if (family == "T03") {
      checked(cudaEventRecord(ready, upload), "record upload completion");
      checked(cudaStreamWaitEvent(download, ready, 0), "download waits for upload");
      sink = download;
    }
    checked(cudaMemcpyAsync(observed, kernel ? result : device, bytes, cudaMemcpyDeviceToHost, sink), "D2H copy");
    checked(cudaStreamSynchronize(sink), "synchronize observation");
    const auto duration = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    bool correct = true;
    for (int i = 0; i < size; ++i) correct &= observed[i] == expected[i];
    pass &= correct;
    std::cout << "{\"record_type\":\"case\",\"scope\":\"REAL_CUDA_CC_NOT_YET_QUALIFIED\",\"gpu_executed\":true,\"seed\":0,\"family\":\"" << family
              << "\",\"repeat\":" << repeat << ",\"size\":" << size << ",\"generation\":" << gen << ",\"kernel\":" << (kernel ? "true" : "false")
              << ",\"duration_seconds\":" << duration << ",\"synchronization\":\"" << (family == "T03" ? "event_wait_then_stream_sync" : "same_stream_then_stream_sync")
              << "\",\"verdict\":\"" << (correct ? "PASS" : "INCONCLUSIVE") << "\",\"oracle_verdict\":\"" << (correct ? "PASS" : "FAIL")
              << "\",\"expected\":";
    array_json(expected.data(), size); std::cout << ",\"observed\":"; array_json(observed, size);
    std::cout << "}" << std::endl;
  }
  checked(cudaStreamSynchronize(upload), "finish upload before release");
  checked(cudaStreamSynchronize(download), "finish download before release");
  checked(cudaEventDestroy(ready), "destroy event");
  checked(cudaStreamDestroy(upload), "destroy upload stream");
  checked(cudaStreamDestroy(download), "destroy download stream");
  checked(cudaFree(device), "release device input");
  checked(cudaFree(result), "release device output");
  checked(cudaFreeHost(host), "release pinned input");
  checked(cudaFreeHost(observed), "release pinned output");
  return pass;
}
int main(int argc, char** argv) {
  if (argc == 2 && std::string(argv[1]) == "--cpu-reference-tests") {
    for (int generation = 0; generation < 32; ++generation)
      for (int i = 0; i < 4096; ++i) {
        const int x = pattern(i, generation);
        if (i == 0 && x != generation) return 1;
        if (i != 0 && (x < -4095 || x > 4095)) return 1;
        if (static_cast<int>(2.0 * static_cast<double>(x) + 1.0) != 2 * x + 1) return 1;
      }
    std::cout << "{\"scope\":\"CPU_REFERENCE_ONLY\",\"gpu_executed\":false,\"verdict\":\"PASS\"}" << std::endl;
    return 0;
  }
  int count = 0;
  const cudaError_t available = cudaGetDeviceCount(&count);
  if (available != cudaSuccess || count == 0) {
    std::cout << "{\"scope\":\"CUDA_PROBE\",\"gpu_executed\":false,\"verdict\":\"UNSUPPORTED\",\"reason\":\"no_usable_CUDA_device\"}" << std::endl;
    return 77;
  }
  try {
    int driver = 0, runtime = 0;
    checked(cudaDriverGetVersion(&driver), "driver version");
    checked(cudaRuntimeGetVersion(&runtime), "runtime version");
    std::cout << "{\"record_type\":\"environment\",\"cuda_driver_version\":" << driver << ",\"cuda_runtime_version\":" << runtime
              << ",\"device_count\":" << count << ",\"attestation\":\"NOT_RUN\",\"T04\":\"NOT_RUN\",\"T07\":\"NOT_RUN\",\"T08\":\"NOT_RUN\"}" << std::endl;
    bool pass = true;
    for (int repeat = 0; repeat < 3; ++repeat) {
      for (const auto& family : {"T01", "T02", "T03", "T05"}) pass &= sequence(128, repeat * 10, family, false, repeat);
      for (int size : {1, 2, 31, 32, 33, 255, 256, 257, 4096}) pass &= sequence(size, repeat, "T06", false, repeat);
      pass &= sequence(4096, repeat, "E0_KERNEL_REFERENCE", true, repeat);
    }
    return pass ? 0 : 1;
  } catch (const std::exception& error) {
    // Keep original error text on protected stderr; do not diagnose it as a defect.
    std::cerr << error.what() << std::endl;
    std::cout << "{\"record_type\":\"error\",\"verdict\":\"INFRA_FAILURE\",\"reason\":\"CUDA_API_error_see_stderr\"}" << std::endl;
    return 2;
  }
}
