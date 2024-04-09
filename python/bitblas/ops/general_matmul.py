# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
import tvm
from tvm.target import Target
from bitblas.base.roller.arch.cuda import CUDA
from typing import Any, List, Literal, Optional, Tuple, Union
from .operator import Operator, TransformKind
from .impl.matmul_dequantize_impl import (
    select_implementation as weight_dequantize_implementation,)
from .impl.matmul_impl import select_implementation as consistent_implementation
from ..base.utils import tensor_replace_dp4a
from bitblas.utils.target_detector import auto_detect_nvidia_target
from bitblas.utils.tensor_adapter import tvm_tensor_to_torch
from dataclasses import dataclass
from .ladder_permutate import LadderPermutate, LadderPermutateConfig
from .lop3_permutate import LOP3Permutate, LOP3PermutateConfig
import logging

logger = logging.getLogger(__name__)


class OPExecutorCPU:

    def __init__(self, operators: Optional[List[Operator]] = None):
        if operators is None:
            operators = []
        self.operators = operators

    def append(self, op):
        self.operators.append(op)

    def is_none(self):
        return len(self.operators) == 0

    def forward(self, weight):
        inputs = [weight]
        for op in self.operators:
            inputs.append(tvm_tensor_to_torch(op.get_profile_tensors()[-1]).cpu())
            inputs = [op.forward(*inputs)]
        return inputs[-1]

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        return self.forward(*args, **kwds)

    @property
    def size(self):
        return len(self.operators)


@dataclass(frozen=True)
class MatmulConfig:
    M: Union[int, Tuple[int]]
    N: int
    K: int
    A_dtype: str = "float16"
    # is a wrapper for source_format and bit
    W_dtype: str = A_dtype  # W_dtype is the same as A_dtype by default
    out_dtype: str = "float16"
    accum_dtype: str = "float16"
    layout: Literal["nn", "nt", "tn", "tt"] = "nt"
    with_bias: bool = False
    group_size: int = -1
    with_scaling: bool = False
    with_zeros: bool = False
    # documents for zeros_mode:
    # original: target = (dequantize_weight - zero_point) * scale
    # rescale: target = dequantize_weight * scale - zero_point
    # quantized: target = (dequantize_weight - dequantize_zeros) * scale
    # The auto-gptq framework prefer "quantized" and "original" for alignment with cuda.
    zeros_mode: Literal["original", "rescale", "quantized"] = "original"
    storage_dtype: str = "int8"

    # weight transform related flags
    fast_decoding: bool = True  # enable fast decoding by default
    propagate_a: TransformKind = TransformKind.NonTransform
    propagate_b: TransformKind = TransformKind.NonTransform

    def __post_init__(self):
        # set M to tuple if it is list
        # otherwise, M is not hashable
        object.__setattr__(self, "M", tuple(self.M) if isinstance(self.M, list) else self.M)
        if isinstance(self.propagate_a, bool):
            object.__setattr__(
                self,
                "propagate_a",
                (TransformKind.IntraWarpTransform
                 if self.propagate_a else TransformKind.NonTransform),
            )
        elif isinstance(self.propagate_a, int):
            object.__setattr__(self, "propagate_a", TransformKind(self.propagate_a))

        if isinstance(self.propagate_b, bool):
            object.__setattr__(
                self,
                "propagate_b",
                (TransformKind.IntraWarpTransform
                 if self.propagate_b else TransformKind.NonTransform),
            )
        elif isinstance(self.propagate_b, int):
            object.__setattr__(self, "propagate_b", TransformKind(self.propagate_b))

        if self.zeros_mode is None:
            object.__setattr__(self, "zeros_mode", "original")

        if "int" not in self.W_dtype:
            object.__setattr__(self, "fast_decoding", False)
        else:
            object.__setattr__(self, "fast_decoding", self.fast_decoding)

        if self.with_bias is None:
            object.__setattr__(self, "with_bias", False)
        
        if self.group_size is None:
            object.__setattr__(self, "group_size", -1)
        
        if self.with_scaling is None:
            object.__setattr__(self, "with_scaling", False)
        
        if self.with_zeros is None:
            object.__setattr__(self, "with_zeros", False)

class Matmul(Operator):

    # TODO(lei): This should be improved into a general datatype.
    BITBLAS_TRICK_DTYPE_MAP = {
        "float64": ("fp", 64),
        "float32": ("fp", 32),
        "float16": ("fp", 16),
        "int32": ("int", 32),
        "uint32": ("uint", 32),
        "int16": ("int", 16),
        "uint16": ("uint", 16),
        "int8": ("int", 8),
        "uint8": ("uint", 8),
        "int4": ("int", 4),
        "uint4": ("uint", 4),
        "int2": ("int", 2),
        "uint2": ("uint", 2),
        "int1": ("int", 1),
        "uint1": ("uint", 1),
        "nf4": ("af", 4),
        "fp8_e5m2": ("fp", 8),
        "fp4_e2m1": ("af", 4),
    }

    def __init__(
        self,
        config: MatmulConfig,
        name: str = "matmul",
        target: Optional[Union[str, Target]] = None,
    ):
        if target is None:
            target = auto_detect_nvidia_target()
        assert (config.A_dtype
                in self.BITBLAS_TRICK_DTYPE_MAP), f"Unsupported input dtype {config.A_dtype}"
        source_format, bit = self.BITBLAS_TRICK_DTYPE_MAP[config.W_dtype]

        self.source_format = source_format
        self.bit = bit
        super().__init__(name, config, target)

        if source_format == "int" and self.with_zeros:
            logger.warning(
                "[BitBLAS][Warning] with_zeros is not supported for int source format as int has a constant zeropoints already."
            )

        target = self.target
        if target.kind.name != "cuda":
            raise ValueError("Currently only support cuda target")

        self.arch = CUDA(target)

        try:
            self.optimized_func = self.apply_default_schedule(self.prim_func_mod, target)
        except Exception:
            self.optimized_func = None
            logger.warnning(
                "[BitBLAS][Warning] Apply default schedule failed, should do hardware-aware optimization manually."
            )

        if isinstance(self.M, Tuple):
            self.dynamic_range = {"m": self.M}
            self.prim_func_mod["main"] = self.prim_func_mod["main"].with_attrs(
                {"opt_shapes": self.dynamic_range})
        else:
            self.dynamic_range = None

        self._build_runtime_module(target)

        if self.propagate_a:
            ladder_permutate_config = LadderPermutateConfig(
                M=self.M,
                N=self.K,
                datatype=self.A_dtype,
                storage_dtype=self.A_dtype,
                propagate_kind="A",
                transpose_matrix=False,
                transform_kind=self.propagate_a,
            )
            self.ladder_permutate_a = LadderPermutate(
                config=ladder_permutate_config,
                target=tvm.target.Target("llvm"),
            )
        else:
            self.ladder_permutate_a = None

        if self.propagate_b:
            ladder_permutate_config = LadderPermutateConfig(
                M=self.N,
                N=self.K,
                datatype=self.A_dtype,
                dequantize_bits=self.bit,
                storage_dtype=self.storage_dtype,
                propagate_kind="B",
                transpose_matrix=self.layout == "nt",
                transform_kind=self.propagate_b,
            )
            self.ladder_permutate_b = LadderPermutate(
                config=ladder_permutate_config,
                target=tvm.target.Target("llvm"),
            )
        else:
            self.ladder_permutate_b = None

        if self.fast_decoding:
            lop3_permutate_config = LOP3PermutateConfig(
                M=self.N,
                N=self.K,
                datatype=self.A_dtype,
                dequantize_bits=self.bit,
                storage_dtype=self.storage_dtype,
            )
            self.lop3_permutate = LOP3Permutate(
                config=lop3_permutate_config,
                target=tvm.target.Target("llvm"),
            )
        else:
            self.lop3_permutate = None

        input_executors = OPExecutorCPU()
        if self.ladder_permutate_a is not None:
            input_executors.append(self.ladder_permutate_a)
        self.input_executors = input_executors

        weight_executors = OPExecutorCPU()
        if self.lop3_permutate is not None:
            weight_executors.append(self.lop3_permutate)

        if self.ladder_permutate_b is not None:
            weight_executors.append(self.ladder_permutate_b)

        self.weight_executors = weight_executors

    def _select_implementation(self):
        if self.A_dtype == self.W_dtype:
            return consistent_implementation(
                M=self.M,
                N=self.N,
                K=self.K,
                in_dtype=self.A_dtype,
                out_dtype=self.out_dtype,
                accum_dtype=self.accum_dtype,
                with_bias=self.with_bias,
                layout=self.layout,
                propagate_a=self.propagate_a,
                propagate_b=self.propagate_b,
            )
        else:
            return weight_dequantize_implementation(
                M=self.M,
                N=self.N,
                K=self.K,
                in_dtype=self.A_dtype,
                out_dtype=self.out_dtype,
                accum_dtype=self.accum_dtype,
                bit=self.bit,
                storage_dtype=self.storage_dtype,
                source_format=self.source_format,
                with_scaling=self.with_scaling,
                with_zeros=self.with_zeros,
                group_size=self.group_size,
                fast_decoding=self.fast_decoding,
                with_bias=self.with_bias,
                layout=self.layout,
                zeros_mode=self.zeros_mode,
                propagate_a=self.propagate_a,
                propagate_b=self.propagate_b,
            )

    def post_process(self, code: str) -> str:
        code = tensor_replace_dp4a(code)
        return code

    def retrieve_weight_shape(self):
        return [int(i) for i in self.prim_func.buffer_map[self.prim_func.params[1]].shape]

    def forward(self, *args) -> Any:
        if self.lib is None:
            self._forward_from_torch_func(*args)
        dynamic_symbolic = []
        if self.dynamic_range is not None:
            # assume we only have one dynamic range
            m = args[0].shape[0]
            dynamic_symbolic.append(m)
        self._forward_from_prebuild_lib(*args, *dynamic_symbolic)

    @property
    def M(self):
        return self.config.M

    @property
    def N(self):
        return self.config.N

    @property
    def K(self):
        return self.config.K

    @property
    def A_dtype(self):
        return self.config.A_dtype

    @property
    def W_dtype(self):
        return self.config.W_dtype

    @property
    def out_dtype(self):
        return self.config.out_dtype

    @property
    def accum_dtype(self):
        return self.config.accum_dtype

    @property
    def storage_dtype(self):
        return self.config.storage_dtype

    @property
    def with_scaling(self):
        return self.config.with_scaling

    @property
    def with_zeros(self):
        return self.config.with_zeros

    @property
    def group_size(self):
        return self.config.group_size

    @property
    def fast_decoding(self):
        return self.config.fast_decoding

    @property
    def with_bias(self):
        return self.config.with_bias

    @property
    def propagate_a(self):
        return self.config.propagate_a

    @property
    def propagate_b(self):
        return self.config.propagate_b

    @property
    def layout(self):
        return self.config.layout

    @property
    def zeros_mode(self):
        return self.config.zeros_mode

    @property
    def input_transform(self):
        return self.input_executors if self.input_executors.size else None

    @property
    def weight_transform(self):
        return self.weight_executors if self.weight_executors.size else None