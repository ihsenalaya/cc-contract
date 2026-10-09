// Line protocol from the prevalidated Python IR. No device resets or CC changes.
#include <cuda_runtime.h>
#include <iostream>
#include <sstream>
#include <string>
#include <map>
#include <vector>
#include <stdexcept>
#include <cstdint>

static bool cpu = false;
struct CudaFailure : std::runtime_error { cudaError_t status; explicit CudaFailure(cudaError_t e) : std::runtime_error(cudaGetErrorString(e)), status(e) {} };
static void ck(cudaError_t e) { if (e != cudaSuccess) throw CudaFailure(e); }
struct Buffer { int *data = nullptr; long long *generation = nullptr; int size; bool host, mapped; };
struct Node { std::string source, target, stream; };
struct Graph { std::vector<Node> nodes; cudaGraph_t graph = nullptr; cudaGraphExec_t executable = nullptr; std::string stream; };
static std::map<std::string,Buffer> buffers;
static std::map<std::string,cudaStream_t> streams;
static std::map<std::string,cudaEvent_t> events;
static std::map<std::string,Graph> graphs;

static cudaStream_t stream(const std::string& name) {
  if (!streams.count(name)) { cudaStream_t s = nullptr; if (!cpu) ck(cudaStreamCreateWithFlags(&s,cudaStreamNonBlocking)); streams[name] = s; }
  return streams.at(name);
}
static void allocate(const std::string& name, const std::string& location, int size, const std::string& memory) {
  if (buffers.count(name) || size < 1 || size > 65536) throw std::runtime_error("invalid allocation");
  Buffer b; b.size = size; b.host = location == "host"; b.mapped = memory == "mapped";
  if (cpu) { b.data = new int[size](); b.generation = new long long(-1); }
  else if (b.host) {
    ck(cudaHostAlloc(&b.data,size*sizeof(int),b.mapped ? cudaHostAllocMapped : cudaHostAllocDefault));
    ck(cudaHostAlloc(&b.generation,sizeof(long long),b.mapped ? cudaHostAllocMapped : cudaHostAllocDefault));
    *b.generation = -1;
  } else { ck(cudaMalloc(&b.data,size*sizeof(int))); ck(cudaMalloc(&b.generation,sizeof(long long))); }
  buffers[name] = b;
}
__global__ void mapped_copy(const int *source, const long long *tag, int *target, long long *target_tag, int n) {
  int i = blockIdx.x*blockDim.x+threadIdx.x;
  if (i < n) target[i] = source[i];
  if (i == 0) *target_tag = *tag;
}
static void copy(const Node& node, bool mapped = false) {
  auto& source = buffers.at(node.source); auto& target = buffers.at(node.target);
  if (source.size != target.size) throw std::runtime_error("copy shape mismatch");
  if (cpu) { for (int i=0;i<source.size;++i) target.data[i]=source.data[i]; *target.generation=*source.generation; return; }
  if (mapped) {
    if (!source.host || !source.mapped || target.host) throw std::runtime_error("invalid mapped kernel");
    int *data; long long *tag;
    ck(cudaHostGetDevicePointer(&data,source.data,0)); ck(cudaHostGetDevicePointer(&tag,source.generation,0));
    mapped_copy<<<(source.size+255)/256,256,0,stream(node.stream)>>>(data,tag,target.data,target.generation,source.size);
    ck(cudaGetLastError());
  } else {
    ck(cudaMemcpyAsync(target.data,source.data,source.size*sizeof(int),cudaMemcpyDefault,stream(node.stream)));
    ck(cudaMemcpyAsync(target.generation,source.generation,sizeof(long long),cudaMemcpyDefault,stream(node.stream)));
  }
}
static void free_buffer(const std::string& name) {
  auto b = buffers.at(name);
  if (cpu) { delete[] b.data; delete b.generation; }
  else if (b.host) { ck(cudaFreeHost(b.data)); ck(cudaFreeHost(b.generation)); }
  else { ck(cudaFree(b.data)); ck(cudaFree(b.generation)); }
  buffers.erase(name);
}
static void cleanup() {
  if (!cpu) for (auto& entry : streams) cudaStreamSynchronize(entry.second);
  for (auto& entry : graphs) if (!cpu) { if(entry.second.executable) cudaGraphExecDestroy(entry.second.executable); if(entry.second.graph) cudaGraphDestroy(entry.second.graph); }
  graphs.clear();
  while (!buffers.empty()) free_buffer(buffers.begin()->first);
  if (!cpu) { for(auto& entry : events) cudaEventDestroy(entry.second); for(auto& entry : streams) cudaStreamDestroy(entry.second); }
  events.clear(); streams.clear();
}
static void define_graph(const std::string& name, const std::string& s, const std::vector<Node>& nodes) {
  if (graphs.count(name)) throw std::runtime_error("duplicate graph");
  Graph g; g.nodes = nodes; g.stream = s;
  if (!cpu) {
    ck(cudaStreamBeginCapture(stream(s),cudaStreamCaptureModeThreadLocal));
    for (const auto& n : nodes) copy(n);
    ck(cudaStreamEndCapture(stream(s),&g.graph));
    ck(cudaGraphInstantiate(&g.executable,g.graph,0));
  }
  graphs[name] = g;
}
static void replay(const std::string& name, int n) {
  if (n < 1 || n > 64) throw std::runtime_error("invalid replay count");
  auto& g = graphs.at(name);
  for(int i=0;i<n;++i) { if(cpu) for(auto& node:g.nodes) copy(node); else ck(cudaGraphLaunch(g.executable,stream(g.stream))); }
}
static void probe(const std::string& feature) {
  allocate("input","host",32,feature=="mapped" ? "mapped" : "pinned");
  allocate("device","device",32,"pinned"); allocate("output","host",32,"pinned");
  for(int i=0;i<32;++i) buffers.at("input").data[i]=i*17-91;
  *buffers.at("input").generation=11;
  Node up{"input","device","probe"}, down{"device","output","probe"};
  if(feature=="graphs") { define_graph("g","probe",{up,down}); replay("g",3); }
  else if(feature=="mapped") { copy(up,true); copy(down); }
  else throw std::runtime_error("unknown capability probe");
  ck(cudaStreamSynchronize(stream("probe")));
  for(int i=0;i<32;++i) if(buffers.at("output").data[i]!=i*17-91) throw std::runtime_error("probe payload mismatch");
  if(*buffers.at("output").generation!=11) throw std::runtime_error("probe generation mismatch");
  cleanup();
}
int main(int argc,char** argv) {
  cpu = argc == 2 && std::string(argv[1]) == "--cpu-reference";
  if(!cpu) { int count=0; auto status=cudaGetDeviceCount(&count); if(status!=cudaSuccess || count!=1) { std::cout<<"{\"record_type\":\"environment\",\"verdict\":\"UNSUPPORTED\",\"gpu_executed\":false,\"reason\":\"exactly_one_usable_device_required\"}"<<std::endl; return 77; } }
  if(argc==3 && std::string(argv[1])=="--probe") {
    try { probe(argv[2]); std::cout<<"{\"scope\":\"REAL_CUDA_CAPABILITY_PROBE\",\"feature\":\""<<argv[2]<<"\",\"gpu_executed\":true,\"verdict\":\"PASS\"}"<<std::endl; return 0; }
    catch(const CudaFailure& e) {
      std::cerr<<e.what()<<std::endl;
      bool unsupported = e.status == cudaErrorNotSupported;
      std::cout<<"{\"scope\":\"REAL_CUDA_CAPABILITY_PROBE\",\"gpu_executed\":true,\"verdict\":\""<<(unsupported?"UNSUPPORTED":"INFRA_FAILURE")<<"\",\"reason\":\"see_preserved_stderr\"}"<<std::endl;
      return unsupported ? 77 : 2;
    }
    catch(const std::exception& e) { std::cerr<<e.what()<<std::endl; std::cout<<"{\"scope\":\"REAL_CUDA_CAPABILITY_PROBE\",\"gpu_executed\":true,\"verdict\":\"INFRA_FAILURE\",\"reason\":\"see_preserved_stderr\"}"<<std::endl; return 2; }
  }
  std::cout<<"{\"record_type\":\"environment\",\"scope\":\""<<(cpu?"CPU_NATIVE_REFERENCE_ONLY":"REAL_CUDA_IR")<<"\",\"gpu_executed\":"<<(cpu?"false":"true")<<",\"hardware_attestation\":\"NOT_RUN_IN_WORKER\"}"<<std::endl;
  try {
    std::string line;
    while(std::getline(std::cin,line)) {
      std::istringstream in(line); std::string command,a,b,c; in>>command;
      if(command=="BEGIN") { if(!buffers.empty() || !graphs.empty()) throw std::runtime_error("prior case unfinished"); }
      else if(command=="ALLOC") { int n; in>>a>>b>>n>>c; if(!in) throw std::runtime_error("bad alloc protocol"); allocate(a,b,n,c); }
      else if(command=="WRITE") { long long gen; int n; in>>a>>gen>>n; auto& target=buffers.at(a); if(!target.host || n!=target.size) throw std::runtime_error("bad write protocol"); for(int i=0;i<n;++i) if(!(in>>target.data[i])) throw std::runtime_error("truncated write"); *target.generation=gen; }
      else if(command=="COPY" || command=="MAPPED") { in>>a>>b>>c; copy({a,b,c},command=="MAPPED"); }
      else if(command=="EVENT") { in>>a>>b; if(events.count(a)) throw std::runtime_error("duplicate event"); cudaEvent_t event=nullptr; if(!cpu) { ck(cudaEventCreateWithFlags(&event,cudaEventDisableTiming)); ck(cudaEventRecord(event,stream(b))); } events[a]=event; }
      else if(command=="WAIT") { in>>a>>b; if(!cpu) ck(cudaStreamWaitEvent(stream(a),events.at(b),0)); }
      else if(command=="SYNC") { in>>a; if(!cpu) ck(cudaStreamSynchronize(stream(a))); }
      else if(command=="GRAPH") { int n; in>>a>>b>>n; if(n<1||n>64) throw std::runtime_error("bad graph protocol"); std::vector<Node> nodes; for(int i=0;i<n;++i) { if(!std::getline(std::cin,line)) throw std::runtime_error("truncated graph"); std::istringstream node(line); std::string op,s,t,st; node>>op>>s>>t>>st; if(op!="COPY"||st!=b) throw std::runtime_error("invalid graph node"); nodes.push_back({s,t,st}); } define_graph(a,b,nodes); }
      else if(command=="REPLAY") { int n; in>>a>>n; replay(a,n); }
      else if(command=="DESTROY_GRAPH") { in>>a; auto g=graphs.at(a); if(!cpu) { ck(cudaGraphExecDestroy(g.executable)); ck(cudaGraphDestroy(g.graph)); } graphs.erase(a); }
      else if(command=="OBSERVE") {
        in>>a; auto& observed=buffers.at(a); if(!observed.host) throw std::runtime_error("observation is not host memory");
        std::cout<<"{\"record_type\":\"observation\",\"buffer\":\""<<a<<"\",\"generation\":"<<*observed.generation<<",\"values\":[";
        for(int i=0;i<observed.size;++i) { if(i) std::cout<<','; std::cout<<observed.data[i]; }
        std::cout<<"]}"<<std::endl;
      }
      else if(command=="FREE") { in>>a; free_buffer(a); }
      else if(command=="END") { if(!buffers.empty()||!graphs.empty()) throw std::runtime_error("unreleased allocations"); cleanup(); std::cout<<"{\"record_type\":\"result\",\"verdict\":\"COMPLETE\"}"<<std::endl; }
      else throw std::runtime_error("unknown protocol command");
    }
    cleanup(); return 0;
  } catch(const std::exception& error) {
    std::cerr<<error.what()<<std::endl;
    std::cout<<"{\"record_type\":\"result\",\"verdict\":\"INFRA_FAILURE\",\"reason\":\"native_protocol_or_CUDA_error\"}"<<std::endl;
    return 2;
  }
}
