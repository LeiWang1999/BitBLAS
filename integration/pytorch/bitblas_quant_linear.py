# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from logging import getLogger

import numpy as np
import torch
import torch.nn as nn


logger = getLogger(__name__)

try:
    import bitblas
except ImportError as e:
    bitblas_import_exception = e

    def error_raiser_bitblas(*args, **kwargs):
        raise ValueError(
            f"Trying to use the bitblas backend, but could not import dependencies with the following error: {bitblas_import_exception}"
        )

    autogptq_bitblas_cuda = bitblas_import_exception

from bitblas.quantization.utils import general_compress, interleave_weight
from bitblas.ops.matmul_dequantize import (
    MatmulWeightOnlyDequantizeConfig,
    MatmulWeightOnlyDequantize,
)
from bitblas.utils import get_target_from_env
from typing import List, Union, Literal, Optional


class QuantLinear(nn.Module):
    QUANT_TYPE = "bitblas"

    def __init__(
        self,
        bits: int,
        group_size: int,
        infeatures: int,
        outfeatures: int,
        bias: bool,
        enable_tuning: bool = False,
        fast_decoding: bool = False,
        propagate_a: bool = False,
        propagate_b: bool = False,
        opt_features: Union[int, List[int]] = [1, 16, 32],
        layout: Literal["nt"] = "nt",
        trainable=False,
        **kwargs,
    ):
        super().__init__()
        if infeatures % 128 != 0 or outfeatures % 256 != 0:
            raise ValueError(
                "`infeatures` must be divisible by 128 and `outfeatures` by 256."
            )
        if bits not in [1, 2, 4]:
            raise NotImplementedError("Only 1/2/4 bits are supported.")
        if infeatures % group_size != 0:
            raise ValueError("`infeatures` must be divisible by `group_size`.")
        if trainable:
            raise NotImplementedError("Bitblas does not support train.")

        self.bits = bits
        storage_nbit = 8  # assume int8 storage
        n_float_per_elem = storage_nbit // bits

        self.opt_features = opt_features
        self.infeatures = infeatures
        self.outfeatures = outfeatures
        self.group_size = group_size if group_size != -1 else infeatures
        self.register_buffer(
            "qweight",
            torch.empty(
                (self.outfeatures, self.infeatures // n_float_per_elem),
                dtype=torch.int8,
            ),
        )
        self.register_buffer(
            "scales",
            torch.empty(
                (self.outfeatures, self.infeatures // self.group_size), dtype=torch.half
            ),
        )
        self.register_buffer(
            "zeros",
            torch.full(
                (self.outfeatures, self.infeatures // self.group_size),
                0,
                dtype=torch.float16,
            ),
        )
        if bias:
            self.register_buffer("bias", torch.zeros((outfeatures), dtype=torch.half))
        else:
            self.bias = None

        self.fast_type_conversion = False
        self.weight_propagation = False

        dtype = self.scales.dtype
        BITBLAS_DTYPES = {
            torch.float32: "float32",
            torch.float16: "float16",
            torch.half: "float16",
            torch.int8: "int8",
        }
        assert dtype in BITBLAS_DTYPES, f"Unsupported dtype: {dtype}"
        bitblas_dtype = BITBLAS_DTYPES[dtype]
        self.target = get_target_from_env()
        matmul_config = MatmulWeightOnlyDequantizeConfig(
            M=self.opt_features,
            N=self.outfeatures,
            K=self.infeatures,
            in_dtype=bitblas_dtype,
            out_dtype=bitblas_dtype,
            accum_dtype="int32" if bitblas_dtype == "int8" else bitblas_dtype,
            bit=bits,
            storage_dtype="int8",
            source_format="uint",
            with_scaling=True,
            with_zeros=True,
            group_size=group_size,
            fast_decoding=fast_decoding,
            with_bias=bias,
            propagate_a=propagate_a,
            propagate_b=propagate_b,
            layout=layout,
            zeros_type="original",
        )
        # optimize target shapes for dynamic symbolic
        self.bitblas_matmul = MatmulWeightOnlyDequantize(
            matmul_config, target=self.target
        )
        if enable_tuning:
            self.bitblas_matmul.hardware_aware_finetune(topk=20)

        self.reset_parameters()

    def reset_parameters(self):
        # init for char
        self.qweight = torch.randint_like(
            self.qweight,
            0,
            2 ** (self.bits - 1) - 1,
            dtype=torch.int8,
            device=self.qweight.device,
        )
        nn.init.normal_(self.scales)
        nn.init.zeros_(self.zeros)
        if self.bias is not None:
            nn.init.zeros_(self.bias)

    def post_init(self):
        pass

    def pack(self, linear, scales, zeros=None):
        """Pack a fake-quantized linear layer into this actual Bitblas representation.
        @linear: fake-quantized `torch.nn.Linear` layer to convert (must be of type `torch.half`)
        @scales: corresponding quantization scales of shape `(infeatures, groups)`
        """
        if linear.weight.dtype != torch.half:
            raise ValueError("Only `torch.half` weights are supported.")

        # do permutation with (n, k) layout
        w = linear.weight.data
        # scales shape should be (n, k) as well.
        s = scales

        scale_zeros = torch.zeros_like(zeros, dtype=torch.float16)
        if zeros is not None:
            scale_zeros[:, :] = zeros[:, :] * scales[:, :]
            self.zeros = zeros.to(scales.device).to(scales.dtype).contiguous()

        # do permutation on weight
        intweight = []
        for idx in range(self.infeatures):
            g_idx = idx // self.group_size
            intweight.append(
                torch.round((w[:, idx] + scale_zeros[:, g_idx]) / scales[:, g_idx]).to(
                    torch.int
                )[:, None]
            )
        intweight = torch.cat(intweight, dim=1)
        intweight = intweight.contiguous()
        intweight = intweight.cpu().numpy().astype(np.int8)
        # quantize to 4bit
        qw_np = general_compress(
            intweight, source_bits=self.bits, storage_dtype=np.int8
        )
        # do interleave for fast type conversion
        if self.fast_type_conversion:
            qw_np = interleave_weight(qw_np, nbits=self.bits, target_dtype="float16")
        if self.weight_propagation:
            # do permutation on weight
            pass

        q = torch.from_numpy(qw_np).to(w.device)
        self.qweight = q.to(self.qweight.device).contiguous()
        self.scales = s.to(self.qweight.device).contiguous()
        self.zeros = self.zeros.to(self.qweight.device).contiguous()
        if self.bias is not None:
            self.bias[:] = linear.bias.data.to(self.bias.device).contiguous()

    def forward(self, A, Output=None):
        args = [A, self.qweight, self.scales, self.zeros]
        if self.bias is not None:
            args.append(self.bias)
        if Output is None:
            Output = torch.empty(
                A.shape[:-1] + (self.qweight.shape[0],), dtype=A.dtype, device=A.device
            )
        args.append(Output)

        self.bitblas_matmul(*args)

        return Output


__all__ = ["QuantLinear"]
