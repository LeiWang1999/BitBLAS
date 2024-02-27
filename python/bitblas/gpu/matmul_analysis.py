# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# pylint: disable=missing-docstring, invalid-name
"""A GEMM schedule rule for GPU operators."""
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Set, Union, Tuple, Dict
from tvm import tir, DataType
from tvm.ir import Range
from tvm.tir import IterVar, PrimExpr, Var
from tvm.tir.analysis import undefined_vars
from tvm.tir.schedule.schedule import BlockRV
from ..base.analysis import (
    collect_block_iter_vars_used_in_access_region,
    get_root_block,
    get_reduction_blocks,
)
from tvm.target.target import Target
from tvm.tir import IndexMap


def _is_one(x: PrimExpr) -> bool:
    return isinstance(x, tir.IntImm) and x.value == 1


def _collect_producers(sch: tir.Schedule, block: tir.schedule.BlockRV):
    result = []
    for producer in sch.get_producers(block):
        result.append(producer)
        result.extend(_collect_producers(sch, producer))
    return result


def _collect_consumers(sch: tir.Schedule, block: tir.schedule.BlockRV):
    result = []
    for consumer in sch.get_consumers(block):
        result.append(consumer)
        result.extend(_collect_consumers(sch, consumer))
    return result


def auto_inline_producers(
    sch: tir.Schedule,
    block: tir.schedule.BlockRV,
    skip_blocks: Optional[List[tir.schedule.BlockRV]] = None,
):
    skip_blocks = skip_blocks or []
    while True:
        inlined_cnt = 0
        producers = _collect_producers(sch, block)
        for producer in producers:
            if any(
                sch.get(producer) == sch.get(skip_block) for skip_block in skip_blocks
            ):
                continue
            try:
                sch.compute_inline(producer)
                inlined_cnt += 1
            except:  # pylint: disable=bare-except
                continue
        if inlined_cnt == 0:
            return


def auto_inline_consumers(
    sch: tir.Schedule,
    block: tir.schedule.BlockRV,
):
    while True:
        inlined_cnt = 0
        consumers = _collect_consumers(sch, block)
        for consumer in consumers:
            try:
                sch.compute_inline(consumer)
                inlined_cnt += 1
            except:  # pylint: disable=bare-except
                continue
        for consumer in consumers:
            try:
                sch.reverse_compute_inline(consumer)
                inlined_cnt += 1
            except:  # pylint: disable=bare-except
                continue
        if inlined_cnt == 0:
            return


def auto_inline_consumer_chain(
    sch: tir.Schedule,
    block: tir.schedule.BlockRV,
):
    auto_inline_consumers(sch, block)
    remaining_consumers = sch.get_consumers(block)

    if len(remaining_consumers) != 0:
        # Some blocks have failed to be inlined to the producer cache-write stage.
        # This could be due to another producer block that has not been scheduled.
        for c in remaining_consumers:
            for p in sch.get_producers(c):
                if sch.get(p) != sch.get(block):
                    sch.compute_inline(p)

        # Try inlining into the cache-write stage again, this time it should succeed.
        auto_inline_consumers(sch, block)


# find the block that required to be reindex and scope.
def find_last_producer_from_buffer(
    sch, main_block, buffer: tir.Buffer
) -> Optional[BlockRV]:
    # block that most near to the arguments
    block = main_block
    buffer = buffer
    while True:
        last_buffer = buffer
        producers = sch.get_producers(block)

        if len(producers) == 0:
            # do not have any producer means it is the first block
            break

        for producer in producers:
            for write in sch.get(producer).writes:
                if write.buffer == buffer:
                    block = producer
                    buffer = sch.get(producer).reads[0].buffer
        if buffer == last_buffer:
            break
    return block


def find_arg_idx_from_buffer_chain(
    sch: tir.Schedule, main_block: tir.schedule.BlockRV, buffer: tir.Buffer
) -> int:
    """traverse to find the arg index from the buffer"""
    producers = sch.get_producers(main_block)

    # a head buffer has no producer blocks
    def find_args_index(sch: tir.Schedule, buffer: tir.Buffer):
        for i, param in enumerate(sch.mod["main"].params):
            if sch.mod["main"].buffer_map[param] == buffer:
                return i
        return None

    is_head_buffer = len(producers) == 0
    if is_head_buffer:
        return find_args_index(sch, buffer)
    for block in sch.get_producers(main_block):
        if len(sch.get(block).reads) != 1 or len(sch.get(block).writes) != 1:
            continue
        for write in sch.get(block).writes:
            if write.buffer == buffer:
                return find_arg_idx_from_buffer_chain(sch, block, buffer)

    # if no buffer producer block found, it means the buffer is an input buffer
    return find_args_index(sch, buffer)


class IterKind(Enum):
    """Iter kinds for GEMM-liked programs.
    We can simplify the computation to C[S, I, J] += A[S, I, K] * B[S, J, K],
    where `I, J, K` are fundamental axes for gemm and `S` represents all
    other spatial axes (e.g. batches)
    kIter_S: spatial axes
    kIter_I: I axes
    kIter_J: J axes
    kIter_K: K axes
    kIter_T: trivial axes (i.e. with extent 1)
    """

    kIter_S = 0
    kIter_I = 1
    kIter_J = 2
    kIter_K = 3
    kIter_T = 4


@dataclass
class IterTrait:
    kind: IterKind
    extent: PrimExpr


def make_iter_fusion_index_map(
    traits: List[IterTrait],
    kind_order: List[IterKind],
) -> tir.IndexMap:
    fused_iters: Dict[IterKind, PrimExpr] = {}
    input_iters: List[tir.Var] = []
    for i, trait in enumerate(traits):
        v_i = tir.Var(f"i{i}", trait.extent.dtype)
        input_iters.append(v_i)
        if trait.kind == IterKind.kIter_T:
            continue
        if trait.kind not in kind_order:
            raise ValueError(f"Unknown iter kind {trait.kind}")
        if trait.kind in fused_iters:
            fused_iters[trait.kind] = fused_iters[trait.kind] * trait.extent + v_i
        else:
            fused_iters[trait.kind] = v_i

    final_indices: List[tir.PrimExpr] = [
        fused_iters.get(kind, tir.IntImm(traits[0].extent.dtype, 0))
        for kind in kind_order
    ]

    return tir.IndexMap(input_iters, final_indices, None)


def detect_iter_traits(block: tir.Block) -> Optional[Tuple[List[IterTrait]]]:
    """Detect iter traits based on the pattern C[S, I, J] += A[S, I, K] * B[S, J, K]

    Parameters
    ----------
    block : tir.Block
        The block to be analyzed

    Returns
    -------
    traits : Optional[Tuple[List[IterTrait]]]
        The detected iter traits for axes in A, B and C. None if the block
        does not match the pattern.

    """

    if len(block.reads) != 2 or len(block.writes) != 1:
        return None

    def get_access_axes(region: List[Range]) -> Set[Var]:
        axes: Set[Var] = set()
        for r in region:
            if not _is_one(r.extent):
                raise ValueError("Expect elemwise block access")
            axes = axes.union(set(undefined_vars(r.min)))
        return axes

    try:
        A_axes = get_access_axes(block.reads[0].region)
        B_axes = get_access_axes(block.reads[1].region)
        C_axes = get_access_axes(block.writes[0].region)
    except ValueError:
        return None

    traits: Dict[Var, IterTrait] = {}
    for iter_var in block.iter_vars:
        var = iter_var.var
        kind: IterKind
        if _is_one(iter_var.dom.extent):
            if iter_var.iter_type == tir.IterVar.CommReduce:
                # for simplified case (e.g. 1x1 conv kernel)
                kind = IterKind.kIter_K
            else:
                kind = IterKind.kIter_T
        elif iter_var.iter_type == iter_var.DataPar:
            if var in A_axes and var in B_axes and var in C_axes:
                kind = IterKind.kIter_S
            elif var in A_axes and var in C_axes:
                kind = IterKind.kIter_I
            elif var in B_axes and var in C_axes:
                kind = IterKind.kIter_J
            else:
                return None
        elif iter_var.iter_type == tir.IterVar.CommReduce:
            if var in A_axes and var in B_axes and var not in C_axes:
                kind = IterKind.kIter_K
            else:
                return None
        else:
            return None
        traits[var] = IterTrait(kind, iter_var.dom.extent)

    # A Gemm-kernel requires have I, J and K axes
    gemm_traits = {IterKind.kIter_I, IterKind.kIter_J, IterKind.kIter_K}
    if {x.kind for x in traits.values()}.intersection(gemm_traits) != gemm_traits:
        return None

    A_traits = [
        traits[iter_var.var] for iter_var in block.iter_vars if iter_var.var in A_axes
    ]
    B_traits = [
        traits[iter_var.var] for iter_var in block.iter_vars if iter_var.var in B_axes
    ]
    C_traits = [
        traits[iter_var.var] for iter_var in block.iter_vars if iter_var.var in C_axes
    ]
    block_traits = [traits[i.var] for i in block.iter_vars]
    return A_traits, B_traits, C_traits, block_traits


def get_index_map(
    block: tir.Block, layout: List[str] = ["n", "t", "n"]
) -> Optional[Tuple[tir.IndexMap, ...]]:
    """Get index maps for the block

    Parameters
    ----------
    block : tir.Block
        The block to be analyzed

    layout : List[str]
        the target layout index map to be used.
        'n' for [i, k] layout
        't' for [k, j] layout
        'a' for auto inference based on whether the last axis is reduction.

    Returns
    -------
    index_maps : Optional[Tuple[tir.IndexMap]]
        The index maps for the block, or None if the block is not a gemm-liked kernel
    """
    traits = detect_iter_traits(block)
    if traits is None:
        return None
    A_traits, B_traits, C_traits, block_traits = traits

    def get_ordered_axes(region: List[Range]) -> Set[Var]:
        axes: List[Var] = []
        for r in region:
            if not _is_one(r.extent):
                raise ValueError("Expect elemwise block access")
            axes.append(r.min)
        return axes

    def is_common_reduce(var: Var) -> bool:
        for iter_var in block.iter_vars:
            if iter_var.var == var and iter_var.iter_type == IterVar.CommReduce:
                return True
        return False

    def check_last_trait(region: List[Range]):
        axes = get_ordered_axes(region)
        return is_common_reduce(axes[-1])

    def infer_layout(layout: str, region: List[Range], kind: str = "A"):
        """
        Infer the layout based on the region and the kind of buffer
        kind: "A", "B", "C"
        """
        primary_iter, secondary_iter, reduction_iter = {
            "A": (IterKind.kIter_I, IterKind.kIter_K, IterKind.kIter_K),
            "B": (IterKind.kIter_K, IterKind.kIter_J, IterKind.kIter_K),
            "C": (IterKind.kIter_I, IterKind.kIter_J, None),
        }[kind]

        spatial_iter = {
            "A": IterKind.kIter_I,
            "B": IterKind.kIter_J,
            "C": None,
        }[kind]

        if layout == "n":
            return [IterKind.kIter_S, primary_iter, secondary_iter]
        elif layout == "t":
            return [IterKind.kIter_S, secondary_iter, primary_iter]
        elif layout == "a":
            # auto inference layout
            # for buffer with reduction axis, we put it as the last axis
            # otherwise, we put it as the first axis
            if kind == "C":
                return [IterKind.kIter_S, primary_iter, secondary_iter]
            else:
                return (
                    [IterKind.kIter_S, spatial_iter, reduction_iter]
                    if check_last_trait(region)
                    else [IterKind.kIter_S, reduction_iter, spatial_iter]
                )
        else:
            raise ValueError(f"Unknown layout {layout}")

    A_index_map = make_iter_fusion_index_map(
        A_traits, infer_layout(layout[0], block.reads[0].region, kind="A")
    )
    B_index_map = make_iter_fusion_index_map(
        B_traits, infer_layout(layout[1], block.reads[1].region, kind="B")
    )
    C_index_map = make_iter_fusion_index_map(
        C_traits, infer_layout(layout[2], block.writes[0].region, kind="C")
    )

    matmul_index_map = make_iter_fusion_index_map(
        block_traits,
        [IterKind.kIter_S, IterKind.kIter_I, IterKind.kIter_J, IterKind.kIter_K],
    )

    return (
        matmul_index_map,
        A_index_map,
        B_index_map,
        C_index_map,
    )


def get_in_out_dtypes(block: tir.Block) -> Tuple[str]:
    """
    Detect In/Out data types for the given block based on the analysis if read/write buffers.
    """
    assert len(block.reads) > 0 and len(block.writes) > 0
    in_dtype = block.reads[0].buffer.dtype
    out_dtype = block.writes[0].buffer.dtype
    return (in_dtype, out_dtype)


def get_dequantize_block(sch, blocks) -> Optional[BlockRV]:
    # check at least two input and one output
    # at lease one input has uint dtype, and the output dtype is float
    def is_dequantize(block: BlockRV) -> bool:
        block_stmt = sch.get(block)
        if len(block_stmt.reads) < 2:
            return False
        has_uint_input = any(
            "uint" in str(region.buffer.dtype) for region in block_stmt.reads
        )
        if not has_uint_input:
            return False
        if len(block_stmt.writes) != 1 or "float" not in str(
            block_stmt.writes[0].buffer.dtype
        ):
            return False
        return True

    dequantize_blocks = [block for block in blocks if is_dequantize(block)]
    return dequantize_blocks[0] if len(dequantize_blocks) == 1 else None


def is_identity_or_transpose_block(block_stmt: tir.Block) -> bool:
    iter_types = {iter_var.iter_type for iter_var in block_stmt.iter_vars}
    if iter_types != {IterVar.DataPar}:
        return False, False
    if not isinstance(block_stmt.body, tir.BufferStore):
        return False, False
    if not isinstance(block_stmt.body.value, tir.BufferLoad):
        return False, False

    def get_access_vars(region: List[Range]) -> List[Var]:
        axes: List[Var] = []
        for r in region:
            if not _is_one(r.extent):
                return None
            axes.extend(undefined_vars(r.min))
        # remove trivial axis
        trivial_vars = set(
            iter_var.var
            for iter_var in block_stmt.iter_vars
            if _is_one(iter_var.dom.extent)
        )
        axes = [axis for axis in axes if axis not in trivial_vars]
        # remove duplicate axis
        axes = [var for i, var in enumerate(axes) if i == 0 or var != axes[i - 1]]
        return axes

    lhs_access_vars = get_access_vars(block_stmt.reads[0].region)[-2:]
    rhs_access_vars = get_access_vars(block_stmt.writes[0].region)[-2:]
    is_identity = list(lhs_access_vars) == list(rhs_access_vars)
    is_transpose = list(lhs_access_vars) != list(rhs_access_vars) and set(
        lhs_access_vars
    ) == set(rhs_access_vars)
    return is_identity, is_transpose


def is_identity_block(block_stmt: tir.Block) -> bool:
    return is_identity_or_transpose_block(block_stmt)[0]


def is_transpose_block(block_stmt: tir.Block) -> bool:
    return is_identity_or_transpose_block(block_stmt)[1]


def inline_transpose_block(sch: tir.Schedule, blocks: List[tir.schedule.BlockRV]):
    result_blocks = []
    for block in blocks:
        if not is_transpose_block(sch.get(block)):
            result_blocks.append(block)
            continue
        try:
            sch.compute_inline(block)
        except:
            try:
                sch.reverse_compute_inline(block)
            except:
                result_blocks.append(block)
    return result_blocks


def normalize_to_matmul(
    sch: tir.Schedule, main_block: BlockRV, layout: List[str] = ["n", "t", "n"]
) -> Optional[tir.Schedule]:
    block_stmt = sch.get(main_block)

    # let layout be 'a' to auto inference the layout
    index_maps = get_index_map(block_stmt, layout=layout)
    if index_maps is None:
        print("[WARNING] Cannot find the appropriate index map for tensorcore")
        return None

    matmul_index_map, a_index_map, b_index_map, c_index_map = index_maps

    # `skip_simplify` to  avoid the bug in the 1x1 conv
    block = sch.reindex(main_block, ("read", 0), skip_simplify=True)
    sch.transform_layout(block, ("write", 0), a_index_map)
    block = sch.reindex(main_block, ("read", 1), skip_simplify=True)
    sch.transform_layout(block, ("write", 0), b_index_map)
    block = sch.reindex(main_block, ("write", 0), skip_simplify=True)
    sch.transform_layout(block, ("read", 0), c_index_map)
    sch.transform_block_layout(main_block, matmul_index_map)
    sch.mod["main"] = sch.mod["main"].with_attr("dlight.tensorcore_prenormlized", True)
    return sch


def get_tensorized_func_and_tags(
    func: tir.PrimFunc,
    target: Target,
    layout: List[str] = ["a", "a", "a"],
    skip_normalize: bool = False,
    allow_gemv: bool = False,
) -> Tuple[tir.PrimFunc, Dict[str, Union[List[int], int]]]:
    from tvm.tir.tensor_intrin.cuda import (  # pylint: disable=import-outside-toplevel
        get_wmma_intrin_group,
    )

    """
        transform function to matmul if necessary (e.g. transform conv2d with im2col)
    """
    # step1. detect whether the function can utilize tensorcore
    sch = tir.Schedule(func)
    root_block = get_root_block(sch)
    blocks = sch.get_child_blocks(root_block)
    reduction_blocks = get_reduction_blocks(sch, blocks)
    if not reduction_blocks or len(reduction_blocks) != 1:
        return func, None

    def _can_be_tensorized(sch: tir.Schedule, block: BlockRV) -> bool:
        block_stmt = sch.get(block)
        conditions = []
        conditions.append(len(block_stmt.reads) == 2)
        conditions.append(len(block_stmt.writes) == 1)
        conditions.append(
            len(
                collect_block_iter_vars_used_in_access_region(
                    block_stmt, block_stmt.writes[0].region
                )
            )
            > 0
        )
        if not all(conditions):
            return False
        return True

    # step2. transform function to tensorcore matmul (e.g. conv2d with im2col)
    def check_sm_version(arch: str) -> int:
        sm_version = arch.replace("sm_", "")
        return int(sm_version) if sm_version.isdigit() else -1

    def analysis_tensorcore_tags(
        sch: tir.Schedule, block: BlockRV, target: Target
    ) -> bool:
        tags: Dict[str, Union[List[int], int]] = {}
        block_stmt = sch.get(block)

        # analysis tensorcore axis
        # todo(lei): maybe we can remove this in the future
        (write_buffer_region,) = block_stmt.writes
        out_axis = len(write_buffer_region.buffer.shape)
        tags["tensorcore_config"] = [out_axis - 2, out_axis - 1]

        # analysis pipeline stage
        # todo(lei): maybe we can integrate this into policy in the future
        tags["pipeline_stage"] = 1
        if target.kind.name == "cuda" and check_sm_version(target.arch) >= 80:
            # enable pipleline stage only for sm_80 devices
            tags["pipeline_stage"] = 2

        # analysis async copy
        # todo(lei): maybe we can integrate this into policy in the future
        tags["use_async_copy"] = 0
        if tags["pipeline_stage"] == 2 and check_sm_version(target.arch) >= 80:
            # async copy only works in software pipeline.
            tags["use_async_copy"] = 1

        # analysis intrin infomation
        def get_ordered_axes(region: List[Range]) -> Set[Var]:
            axes: List[Var] = []
            for r in region:
                if not _is_one(r.extent):
                    raise ValueError("Expect elemwise block access")
                axes.append(r.min)
            return axes

        def is_common_reduce(var: Var) -> bool:
            for iter_var in block_stmt.iter_vars:
                if iter_var.var == var and iter_var.iter_type == IterVar.CommReduce:
                    return True
            return False

        def check_last_trait(region: List[Range]):
            axes = get_ordered_axes(region)
            return is_common_reduce(axes[-1])

        intrin_info: dict = {}
        in_dtype, out_dtype = get_in_out_dtypes(block_stmt)
        intrin_info["in_dtype"] = in_dtype
        intrin_info["out_dtype"] = out_dtype
        # if the last dimension is reduce axis, the B is transposed
        intrin_info["trans_b"] = check_last_trait(block_stmt.reads[1].region)
        if func.attrs is not None and "smooth_a" in func.attrs:
            intrin_info["smooth_a"] = func.attrs["smooth_a"]
        if func.attrs is not None and "smooth_b" in func.attrs:
            intrin_info["smooth_b"] = func.attrs["smooth_b"]
        tags["intrin_info"] = intrin_info

        return tags

    (main_block,) = reduction_blocks
    if _can_be_tensorized(sch, main_block) is None:
        return func, None

    block_stmt = sch.get(main_block)
    if target.kind.name == "cuda" and check_sm_version(target.arch) >= 70:
        in_dtype, out_dtype = get_in_out_dtypes(block_stmt)
        try:
            _ = get_wmma_intrin_group(
                in_dtype=in_dtype,
                out_dtype=out_dtype,
            )
        except:
            print("[BitBLAS][WARNING] Cannot find the corresponding wmma intrin group")
            return func, None

        # reindex and transform functions
        # Normalize tensor functions to C[S, I, J] += A[S, I, K] * B[S, J, K]
        # or C[S, I, J] += A[S, I, K] * B[S, K, J]
        # skip normalize when we want to detect tags only.
        if not skip_normalize:
            sch = normalize_to_matmul(sch, main_block, layout)
            if sch is None:
                return func, None

        block_stmt = sch.get(main_block)

        minimal_tensorize_threshold = 16
        # the batch dimension is not taken into consideration.
        extent = block_stmt.iter_vars[1].dom.extent
        if isinstance(extent, tir.expr.IntImm):
            if extent.value < (1 if allow_gemv else minimal_tensorize_threshold):
                return func, None
        for item_var in block_stmt.iter_vars[2:]:
            extent = item_var.dom.extent
            if isinstance(extent, tir.expr.IntImm):
                if extent.value < minimal_tensorize_threshold:
                    return func, None
        tags = analysis_tensorcore_tags(sch, main_block, target)
        return sch.mod["main"], tags

    return func, None


def get_propagate_map(
    trans: bool = True, dtype="float16", matrix_name="A", index_dtype="int32"
):
    from tvm.tir.tensor_intrin.cuda import (  # pylint: disable=import-outside-toplevel
        ldmatrix_32x8_to_shared_16x16_layout,
        ldmatrix_trans_32x8_to_shared_16x16_layout,
        ldmatrix_32x16_to_shared_16x32_layout_a,
        ldmatrix_32x16_to_shared_16x32_layout_b,
    )

    assert dtype in ["float16", "int8"], "Only support float16 for now"
    if dtype == "float16":
        ldmatrix_layout = ldmatrix_32x8_to_shared_16x16_layout
        ldmatrix_layout_trans = ldmatrix_trans_32x8_to_shared_16x16_layout
    elif dtype == "int8":
        # int8 mma only support 32x16 to 16x32 layout
        if matrix_name == "A" and trans == False:
            ldmatrix_layout = ldmatrix_32x16_to_shared_16x32_layout_a
        elif matrix_name == "B" and trans == True:
            ldmatrix_layout = ldmatrix_32x16_to_shared_16x32_layout_b
        else:
            raise ValueError("Unknown matrix name ", matrix_name)

    # IntraWarp memory layout was occurred by ldmatrix, we should lift the ld_matrix out
    def ldmatrix_permutation_16x16_32x8_16x16(kernel_i, kernel_j):
        thread_id = kernel_i * 2 + kernel_j // 8
        local_id = kernel_j % 8
        return ldmatrix_layout(thread_id, local_id)

    def ldmatrix_trans_permutation_16x16_32x8_16x16(kernel_i, kernel_j):
        thread_id = kernel_i * 2 + kernel_j // 8
        local_id = kernel_j % 8
        return ldmatrix_layout_trans(thread_id, local_id)

    def ldmatrix_permutation_16x32_32x16_32x16(kernel_i, kernel_j):
        thread_id = kernel_i * 2 + kernel_j // 16
        local_id = kernel_j % 16
        return ldmatrix_layout(thread_id, local_id)

    if dtype == "float16":
        ldmatrix_index_map = (
            ldmatrix_trans_permutation_16x16_32x8_16x16
            if trans
            else ldmatrix_permutation_16x16_32x8_16x16
        )
    else:
        ldmatrix_index_map = ldmatrix_permutation_16x32_32x16_32x16

    ldmatrix_index_map = IndexMap.from_func(ldmatrix_index_map, index_dtype=index_dtype)
    # TODO(lei): index_dtype should be analyzed from the schedule
    row, col = [16, 16] if dtype == "float16" else [16, 32]
    inversed_index_map = ldmatrix_index_map.inverse([row, col])
    return ldmatrix_index_map, inversed_index_map


def layout_propagate_chain(
    sch: tir.Schedule,
    start_block: BlockRV,
    start_buffer: tir.Buffer,
    end_block: BlockRV,
    index_map: IndexMap,
):
    # some layout transformation may only apply to the last n dimensions
    # propagate the layout transformation to the chain of blocks
    block = start_block
    buffer = start_buffer
    index_map = index_map
    while True:
        last_buffer = buffer
        producers = sch.get_producers(block)
        if len(producers) == 0:
            break
        for producer in producers:
            if len(sch.get(producer).writes) != 1:
                return index_map
            if sch.get(producer) == sch.get(end_block):
                return index_map
            (write,) = sch.get(producer).writes
            read = sch.get(producer).reads[0]
            if write.buffer == buffer:
                block = producer
                buffer = sch.get(producer).reads[0].buffer
                write_indices = [r.min for r in write.region]
                read_indices = [r.min for r in read.region]
                # reverse index map from [vi // x] -> [vi * x] to match the inconsistent layout
                tmp_index_map = IndexMap(write_indices, read_indices, None)
                tmp_index_map = tmp_index_map.non_surjective_inverse(
                    write.buffer.shape
                )[0]

                # if dequantize like ops are used, the scaling factor should be considered
                # to be applied to the final indices
                scaling_factor = 1
                for i, j in zip(write.buffer.shape, read.buffer.shape):
                    scaling_factor *= i // j
                final_indices = list(
                    index_map.map_indices(tmp_index_map.map_indices(write_indices))
                )
                final_indices[-1] = final_indices[-1] // scaling_factor
                index_map = IndexMap(
                    write_indices,
                    final_indices,
                    None,
                )
        if buffer == last_buffer:
            break
    return index_map
