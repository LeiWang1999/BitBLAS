# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
import tvm
import bitblas
from bitblas.base.roller.policy import TensorCorePolicy, DefaultPolicy
from bitblas.base.roller.arch import CUDA
from bitblas.gpu.matmul_analysis import get_tensorized_func_and_tags
from bitblas.gpu import Matmul
from bitblas.utils import auto_detect_nvidia_target
from bitblas.base.utils import apply_and_build
from bitblas.ops.impl.matmul_dequantize_impl import (
    matmul_nt_dequantize_b,
    matmul_nt_dequantize_b_propagate_a_propagate_b,
)
import time
import argparse

parser = argparse.ArgumentParser(description="Benchmark BitBLAS int4 on a specific target.")
parser.add_argument(
    "--target",
    type=str,
    default=auto_detect_nvidia_target(),
)
parser.add_argument(
    "--batch_seq",
    type=int,
    default=1,
    help="The batch size of the sequence",
)
parser.add_argument(
    "--group_size",
    type=int,
    default=-1,
    help="The group size of the sequence",
)
parser.add_argument(
    "--benchmark_sets",
    nargs="+",
    default=["llm_shape_fp16xnf4"],
    help="List of benchmark sets, e.g., llm_shape_fp16xnf4",
)

args = parser.parse_args()
group_size = args.group_size

# fmt:off
llm_shape_fp16xnf4 = [
    # square test
    (matmul_nt_dequantize_b, (1, 16384, 16384, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    # BLOOM-176B
    (matmul_nt_dequantize_b, (1, 43008, 14336, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    (matmul_nt_dequantize_b, (1, 14336, 14336, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    (matmul_nt_dequantize_b, (1, 57344, 14336, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    (matmul_nt_dequantize_b, (1, 14336, 57344, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    # # OPT-65B
    (matmul_nt_dequantize_b, (1, 9216, 9216, "float16", "float16", "float16", 4, "int8", "nf", True,
                              False, group_size, False, False), Matmul),
    (matmul_nt_dequantize_b, (1, 36864, 9216, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    (matmul_nt_dequantize_b, (1, 9216, 36864, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    (matmul_nt_dequantize_b, (1, 22016, 8192, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    # LLAMA-70B/65B
    (matmul_nt_dequantize_b, (1, 8192, 22016, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    (matmul_nt_dequantize_b, (1, 8192, 8192, "float16", "float16", "float16", 4, "int8", "nf", True,
                              False, group_size, False, False), Matmul),
    (matmul_nt_dequantize_b, (1, 28672, 8192, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),
    (matmul_nt_dequantize_b, (1, 8192, 28672, "float16", "float16", "float16", 4, "int8", "nf",
                              True, False, group_size, False, False), Matmul),

    # square test
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (16384, 16384, 16384, "float16", "float16", "float16", 4, "int8", "nf", True, False,
      group_size, False, False), Matmul),
    # BLOOM-176B
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 43008, 14336, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 14336, 14336, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 57344, 14336, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 14336, 57344, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    # OPT-65B
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 9216, 9216, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 36864, 9216, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 9216, 36864, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 22016, 8192, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    # LLAMA-70B/65B
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 8192, 22016, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 8192, 8192, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 28672, 8192, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
    (matmul_nt_dequantize_b_propagate_a_propagate_b,
     (8192, 8192, 28672, "float16", "float16", "float16", 4, "int8", "nf", True, False, group_size,
      False, False), Matmul),
]

target = tvm.target.Target(args.target)
benchmark_sets = []
for benchmark_set in args.benchmark_sets:
    benchmark_sets.extend(eval(benchmark_set))
benchmark_results = {}
# fmt:on

target = tvm.target.Target(auto_detect_nvidia_target())

benchmark_results = {}
for get_prim_func, input_args, d_schedule in benchmark_sets:
    ir_module = get_prim_func(*input_args)
    func = ir_module["main"]
    arch = CUDA(target)
    policy = DefaultPolicy(func=func, arch=arch)
    try:
        tensorized_func, tags = get_tensorized_func_and_tags(func, arch.target)
    except Exception:
        tags = None
    if tags:
        policy = TensorCorePolicy(func=tensorized_func, arch=arch, tags=tags)

    configs = policy.emit_config(20)

    tune_start = time.time()
    cpresults, best = apply_and_build(func, configs, arch, parallel_build=True)
    fast_tune_time = time.time() - tune_start
    print("[BitBLAS] The best latency of top 1 is {:.3f} ms".format(cpresults[0].latency))
    print("[BitBLAS] The best latency of top 20 is {:.3f} ms".format(best.latency))

    # evaluate the performance of the default schedule

    rule = d_schedule()
    default_tune_start = time.time()
    with arch.target:
        mod = bitblas.ApplyDefaultSchedule(  # pylint: disable=not-callable
            bitblas.gpu.Matmul(),
            bitblas.gpu.GEMV(),
            bitblas.gpu.Reduction(),
            bitblas.gpu.GeneralReduction(),
            bitblas.gpu.Fallback(),
        )(
            ir_module)
    try:
        with tvm.transform.PassContext(config={"tir.use_async_copy": True}):
            mod_default = tvm.build(mod, target="cuda")
    except Exception:
        mod_default = None

    default_tune_time = time.time() - default_tune_start

    args = func.buffer_map.values()

    profile_tensors = best.profile_tensors
    if mod_default is not None:
        timer_cuda_mod = mod_default.time_evaluator(mod_default.entry_name, arch.device, number=5)
        t = timer_cuda_mod(*profile_tensors).mean
    else:
        t = 1e4 - 1

    print("Time cost of Dlight default schedule: {:.3f} ms".format(t * 1e3))

    profile_config = {
        f"{get_prim_func.__name__}-{'-'.join([str(i) for i in input_args])}": {
            "fast_dlight_top20_tune_time": fast_tune_time,
            "fast_dlight_top1_latency": cpresults[0].latency,
            "fast_dlight_top20_latency": best.latency,
            "default_dlight_tune_time": default_tune_time,
            "default_dlight_latency": t * 1e3 if t is not None else "Failed",
        }
    }

    benchmark_results.update(profile_config)

headers = [
    "PrimFunc",
    "Input Arguments",
    "BitBLAS Top20 Tune Time",
    "BitBLAS Top1 Latency",
    "BitBLAS Top20 Latency",
    "DefaultDLight Tune Time",
    "DefaultDLight Latency",
]

col_width = (max(len(word) for row in [headers] + list(profile_config.values()) for word in row) + 2
            )  # padding

print("".join(word.ljust(col_width) for word in headers))

print("-" * col_width * len(headers))

for config, values in benchmark_results.items():
    args = config.split("-")
    func_name = args[0]
    input_args = "-".join(args[1:])
    row = [
        func_name,
        input_args,
        f" {str(values['fast_dlight_top20_tune_time'])} s",
        f"{values['fast_dlight_top1_latency']:.3f} ms",
        f"{values['fast_dlight_top20_latency']:.3f} ms",
        str(values["default_dlight_tune_time"]),
        f"{values['default_dlight_latency']:.3e} ms",
    ]
    print("".join(word.ljust(col_width) for word in row))
