
#include <cuda_runtime.h>
#include <assert.h>
#include "ladder_kernel.h"
#include "mma.h"
// nvcc ladder_kernel.cu  -gencode arch=compute_80,code=sm_80

__global__ void __launch_bounds__(128) bitblas_kernel_fp16_int2_fp16_m1n15360k5120_nt(half* __restrict__ A, half* __restrict__ QB, half* __restrict__ D) {
            signed char* B = ((int8_t *)QB);
	 half* Scale = (half *)((int8_t *)QB + 19660800);                 
            // const dim3 GridDim(7680, 1, 1);
            // const dim3 BlockDim(64, 2, 1);
            // bitblas_kernel_fp16_int2_fp16_m1n15360k5120_nt<<<GridDim, BlockDim>>>(input_0, input_1, output);
        
  half in_thread_C_local[1];
  int B_local[1];
  half B_decode_local[8];
  half A_local[8];
  __shared__ half red_result[2];
  in_thread_C_local[0] = __float2half_rn(0.000000e+00f);
  for (int ax1_0 = 0; ax1_0 < 10; ++ax1_0) {
    B_local[0] = *(int*)(B + ((((((int)blockIdx.x) * 5120) + (((int)threadIdx.y) * 2560)) + (ax1_0 * 256)) + (((int)threadIdx.x) * 4)));
    decode_i4s_to_f16_scale(B_local, B_decode_local, (&(Scale[((((((int)blockIdx.x) * 80) + (((int)threadIdx.y) * 40)) + (ax1_0 * 4)) + (((int)threadIdx.x) >> 4))])), 8);
    *(uint4*)(A_local + 0) = *(uint4*)(A + ((ax1_0 * 512) + (((int)threadIdx.x) * 8)));
    for (int ax1_2 = 0; ax1_2 < 8; ++ax1_2) {
      in_thread_C_local[0] = (in_thread_C_local[0] + (A_local[ax1_2] * B_decode_local[ax1_2]));
    }
  }
  half red_buf0[1];
  uint mask[1];
  half t0[1];
  half red_buf0_1[1];
  uint mask_1[1];
  half t0_1[1];
  __shared__ half red_buf_staging[4];
  red_buf0_1[0] = in_thread_C_local[0];
  mask_1[0] = __activemask();
  t0_1[0] = __shfl_down_sync(mask_1[0], red_buf0_1[0], 16, 32);
  red_buf0_1[0] = (red_buf0_1[0] + t0_1[0]);
  t0_1[0] = __shfl_down_sync(mask_1[0], red_buf0_1[0], 8, 32);
  red_buf0_1[0] = (red_buf0_1[0] + t0_1[0]);
  t0_1[0] = __shfl_down_sync(mask_1[0], red_buf0_1[0], 4, 32);
  red_buf0_1[0] = (red_buf0_1[0] + t0_1[0]);
  t0_1[0] = __shfl_down_sync(mask_1[0], red_buf0_1[0], 2, 32);
  red_buf0_1[0] = (red_buf0_1[0] + t0_1[0]);
  t0_1[0] = __shfl_down_sync(mask_1[0], red_buf0_1[0], 1, 32);
  red_buf0_1[0] = (red_buf0_1[0] + t0_1[0]);
  if ((((int)threadIdx.x) % 32) == 0) {
    red_buf_staging[((((int)threadIdx.y) * 2) + (((int)threadIdx.x) >> 5))] = red_buf0_1[0];
  }
  __syncthreads();
  if (((int)threadIdx.x) < 2) {
    red_buf0[0] = red_buf_staging[((((int)threadIdx.y) * 2) + ((int)threadIdx.x))];
  }
  mask[0] = (__activemask() & ((uint)(3 << (((int)threadIdx.y) * 2))));
  t0[0] = __shfl_down_sync(mask[0], red_buf0[0], 1, 32);
  red_buf0[0] = (red_buf0[0] + t0[0]);
  if (((int)threadIdx.x) == 0) {
    ((volatile half*)red_result)[((int)threadIdx.y)] = red_buf0[0];
  }
  __syncthreads();
  if (((int)threadIdx.x) == 0) {
    D[((((int)blockIdx.x) * 2) + ((int)threadIdx.y))] = (half)(((volatile half*)red_result)[((int)threadIdx.y)]);
  }
}



__global__ void __launch_bounds__(128) bitblas_kernel_fp16_int2_fp16_m128n15360k5120_nt(half* __restrict__ A, half* __restrict__ QB, half* __restrict__ D) {
            signed char* B = ((int8_t *)QB);
	 half* Scale = (half *)((int8_t *)QB + 19660800);                 
            // const dim3 GridDim(160, 2, 1);
            // const dim3 BlockDim(1, 2, 2);
            // bitblas_kernel_fp16_int2_fp16_m128n15360k5120_nt<<<GridDim, BlockDim>>>(input_0, input_1, output);
        

        const int MAX_BLOCK_N = 10;
        const auto baseBlockIdx = blockIdx.x + gridDim.x *blockIdx.y;
        const auto totalPanel = (gridDim.x * gridDim.y +MAX_BLOCK_N * gridDim.x - 1) / (MAX_BLOCK_N * gridDim.x);
        const auto totalBlock = gridDim.x * gridDim.y;
        const auto panelIdx = baseBlockIdx / (MAX_BLOCK_N *gridDim.x);
        const auto strideLd = panelIdx + 1 < totalPanel ?MAX_BLOCK_N : (totalBlock - panelIdx * (MAX_BLOCK_N *gridDim.x)) / gridDim.x;
        const auto bx = (panelIdx & 1) ? gridDim.x -(baseBlockIdx - panelIdx * MAX_BLOCK_N * gridDim.x) /strideLd - 1 : (baseBlockIdx - panelIdx * MAX_BLOCK_N *gridDim.x) / strideLd;
        const auto by = (baseBlockIdx - panelIdx * MAX_BLOCK_N *gridDim.x) % strideLd + panelIdx * MAX_BLOCK_N;
        const auto bz = blockIdx.z;
        const dim3 blockIdx(bx, by, bz);
      half C_reindex_shared_warp[48];
  __shared__ half A_reindex_shared[4096];
  __shared__ signed char B_shared[4096];
  __shared__ half B_decode_reindex_shared[3072];
  int B_local[1];
  uint4 B_decode_reindex_local[1];
  half A_reindex_shared_warp[16];
  half B_decode_reindex_shared_warp[24];
  int B_local_1[1];
  uint4 B_decode_reindex_local_1[1];
  half A_reindex_shared_warp_1[16];
  half B_decode_reindex_shared_warp_1[24];
  for (int var = 0; var < 1; ++var) {
    for (int ax1_0_3_init = 0; ax1_0_3_init < 2; ++ax1_0_3_init) {
      for (int ax2_0_3_init = 0; ax2_0_3_init < 3; ++ax2_0_3_init) {
        for (int i = 0; i < 8; ++i) {
C_reindex_shared_warp[((ax1_0_3_init * 24) + (ax2_0_3_init * 8)) + i] = 0.0;}
;
      }
    }
    #pragma unroll
    for (int ax0_ax1_ax2_fused_0 = 0; ax0_ax1_ax2_fused_0 < 2; ++ax0_ax1_ax2_fused_0) {

  {
        unsigned int addr;
#if TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST
    addr = static_cast<unsigned int>(__cvta_generic_to_shared((void *)(A_reindex_shared + (((((ax0_ax1_ax2_fused_0 * 1024) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.z) * 256)) + ((((int)threadIdx.x) >> 2) * 32)) + (((((int)threadIdx.x) & 3) ^ (((int)threadIdx.x) >> 3)) * 8)))));
#else
    __asm__ __volatile__(
      "{ .reg .u64 addr; cvta.to.shared.u64 addr, %1; cvt.u32.u64 %0, addr; }\n"
      : "=r"(addr)
      : "l"((void *)(A_reindex_shared + (((((ax0_ax1_ax2_fused_0 * 1024) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.z) * 256)) + ((((int)threadIdx.x) >> 2) * 32)) + (((((int)threadIdx.x) & 3) ^ (((int)threadIdx.x) >> 3)) * 8))))
    );
#endif
    __asm__ __volatile__(
      #if TVM_ENABLE_L2_PREFETCH
        "cp.async.cg.shared.global.L2::128B [%0], [%1], %2;"
      #else
        "cp.async.cg.shared.global [%0], [%1], %2;"
      #endif
        :: "r"(addr), "l"((void*)(A + ((((((((int)blockIdx.y) * 327680) + (ax0_ax1_ax2_fused_0 * 163840)) + (((int)threadIdx.y) * 81920)) + (((int)threadIdx.z) * 40960)) + ((((int)threadIdx.x) >> 2) * 5120)) + ((((int)threadIdx.x) & 3) * 8)))), "n"(16)
    );
  }
    }
    #pragma unroll
    for (int ax0_ax1_fused_0 = 0; ax0_ax1_fused_0 < 1; ++ax0_ax1_fused_0) {
      if (((((int)threadIdx.z) * 2) + ((int)threadIdx.y)) < 3) {

  {
        unsigned int addr;
#if TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST
    addr = static_cast<unsigned int>(__cvta_generic_to_shared((void *)(B_shared + (((((int)threadIdx.z) * 1024) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.x) * 16)))));
#else
    __asm__ __volatile__(
      "{ .reg .u64 addr; cvta.to.shared.u64 addr, %1; cvt.u32.u64 %0, addr; }\n"
      : "=r"(addr)
      : "l"((void *)(B_shared + (((((int)threadIdx.z) * 1024) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.x) * 16))))
    );
#endif
    __asm__ __volatile__(
      #if TVM_ENABLE_L2_PREFETCH
        "cp.async.cg.shared.global.L2::128B [%0], [%1], %2;"
      #else
        "cp.async.cg.shared.global [%0], [%1], %2;"
      #endif
        :: "r"(addr), "l"((void*)(B + ((((((int)blockIdx.x) * 245760) + (((int)threadIdx.z) * 163840)) + (((int)threadIdx.y) * 81920)) + (((int)threadIdx.x) * 2560)))), "n"(16)
    );
  }
      }
    }
__asm__ __volatile__("cp.async.commit_group;");

    for (int ax3_0_0 = 0; ax3_0_0 < 159; ++ax3_0_0) {
      __syncthreads();
      #pragma unroll
      for (int ax0_ax1_ax2_fused_0_1 = 0; ax0_ax1_ax2_fused_0_1 < 2; ++ax0_ax1_ax2_fused_0_1) {

  {
        unsigned int addr;
#if TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST
    addr = static_cast<unsigned int>(__cvta_generic_to_shared((void *)(A_reindex_shared + ((((((((ax3_0_0 + 1) & 1) * 2048) + (ax0_ax1_ax2_fused_0_1 * 1024)) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.z) * 256)) + ((((int)threadIdx.x) >> 2) * 32)) + (((((int)threadIdx.x) & 3) ^ (((int)threadIdx.x) >> 3)) * 8)))));
#else
    __asm__ __volatile__(
      "{ .reg .u64 addr; cvta.to.shared.u64 addr, %1; cvt.u32.u64 %0, addr; }\n"
      : "=r"(addr)
      : "l"((void *)(A_reindex_shared + ((((((((ax3_0_0 + 1) & 1) * 2048) + (ax0_ax1_ax2_fused_0_1 * 1024)) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.z) * 256)) + ((((int)threadIdx.x) >> 2) * 32)) + (((((int)threadIdx.x) & 3) ^ (((int)threadIdx.x) >> 3)) * 8))))
    );
#endif
    __asm__ __volatile__(
      #if TVM_ENABLE_L2_PREFETCH
        "cp.async.cg.shared.global.L2::128B [%0], [%1], %2;"
      #else
        "cp.async.cg.shared.global [%0], [%1], %2;"
      #endif
        :: "r"(addr), "l"((void*)(A + ((((((((((int)blockIdx.y) * 327680) + (ax0_ax1_ax2_fused_0_1 * 163840)) + (((int)threadIdx.y) * 81920)) + (((int)threadIdx.z) * 40960)) + ((((int)threadIdx.x) >> 2) * 5120)) + (ax3_0_0 * 32)) + ((((int)threadIdx.x) & 3) * 8)) + 32))), "n"(16)
    );
  }
      }
      #pragma unroll
      for (int ax0_ax1_fused_0_1 = 0; ax0_ax1_fused_0_1 < 1; ++ax0_ax1_fused_0_1) {
        if (((((int)threadIdx.z) * 2) + ((int)threadIdx.y)) < 3) {

  {
        unsigned int addr;
#if TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST
    addr = static_cast<unsigned int>(__cvta_generic_to_shared((void *)(B_shared + ((((((ax3_0_0 + 1) & 1) * 2048) + (((int)threadIdx.z) * 1024)) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.x) * 16)))));
#else
    __asm__ __volatile__(
      "{ .reg .u64 addr; cvta.to.shared.u64 addr, %1; cvt.u32.u64 %0, addr; }\n"
      : "=r"(addr)
      : "l"((void *)(B_shared + ((((((ax3_0_0 + 1) & 1) * 2048) + (((int)threadIdx.z) * 1024)) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.x) * 16))))
    );
#endif
    __asm__ __volatile__(
      #if TVM_ENABLE_L2_PREFETCH
        "cp.async.cg.shared.global.L2::128B [%0], [%1], %2;"
      #else
        "cp.async.cg.shared.global [%0], [%1], %2;"
      #endif
        :: "r"(addr), "l"((void*)(B + ((((((((int)blockIdx.x) * 245760) + (((int)threadIdx.z) * 163840)) + (((int)threadIdx.y) * 81920)) + (((int)threadIdx.x) * 2560)) + (ax3_0_0 * 16)) + 16))), "n"(16)
    );
  }
        }
      }
__asm__ __volatile__("cp.async.commit_group;");

__asm__ __volatile__("cp.async.wait_group 1;");

      __syncthreads();
      for (int ax1_ax2_0_fused_0 = 0; ax1_ax2_0_fused_0 < 3; ++ax1_ax2_0_fused_0) {
        B_local[0] = *(int*)(B_shared + ((((((ax3_0_0 & 1) * 2048) + (ax1_ax2_0_fused_0 * 512)) + (((int)threadIdx.y) * 256)) + (((int)threadIdx.z) * 128)) + (((int)threadIdx.x) * 4)));
        decode_i4s_to_f16_scale(B_local, B_decode_reindex_local, (&(Scale[((((((((int)blockIdx.x) * 3840) + (ax1_ax2_0_fused_0 * 1280)) + (((int)threadIdx.y) * 640)) + (((int)threadIdx.z) * 320)) + ((((int)threadIdx.x) >> 2) * 40)) + (ax3_0_0 >> 2))])), 8);
        *(uint4*)(B_decode_reindex_shared + (((((ax1_ax2_0_fused_0 * 1024) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.z) * 256)) + ((((int)threadIdx.x) >> 2) * 32)) + (((((int)threadIdx.x) & 3) ^ (((int)threadIdx.x) >> 3)) * 8))) = B_decode_reindex_local[0];
      }
      __syncthreads();
      for (int ax3_0_1 = 0; ax3_0_1 < 2; ++ax3_0_1) {
        for (int ax1_0 = 0; ax1_0 < 2; ++ax1_0) {

  {
    unsigned int addr;
#if TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST
    addr = static_cast<unsigned int>(__cvta_generic_to_shared((void *)((&(A_reindex_shared[((((((ax3_0_0 & 1) * 2048) + (((int)threadIdx.y) * 1024)) + (ax1_0 * 512)) + ((((int)threadIdx.x) & 15) * 32)) + ((((ax3_0_1 * 2) + (((int)threadIdx.x) >> 4)) ^ ((((int)threadIdx.x) & 7) >> 1)) * 8))])) + 0)));
#else
    __asm__ __volatile__(
      "{ .reg .u64 addr; cvta.to.shared.u64 addr, %1; cvt.u32.u64 %0, addr; }\n"
      : "=r"(addr)
      : "l"((void *)((&(A_reindex_shared[((((((ax3_0_0 & 1) * 2048) + (((int)threadIdx.y) * 1024)) + (ax1_0 * 512)) + ((((int)threadIdx.x) & 15) * 32)) + ((((ax3_0_1 * 2) + (((int)threadIdx.x) >> 4)) ^ ((((int)threadIdx.x) & 7) >> 1)) * 8))])) + 0))
    );
#endif
    __asm__ __volatile__(
      "ldmatrix.sync.aligned.m8n8.x4.shared.b16"
      "{%0, %1, %2, %3}, [%4];\n"
      : "=r"(((unsigned *)(A_reindex_shared_warp + (ax1_0 * 8)))[0]), "=r"(((unsigned *)(A_reindex_shared_warp + (ax1_0 * 8)))[1]), "=r"(((unsigned *)(A_reindex_shared_warp + (ax1_0 * 8)))[2]), "=r"(((unsigned *)(A_reindex_shared_warp + (ax1_0 * 8)))[3])
      : "r"(addr)
    );
  }
        }
        for (int ax1_0_1 = 0; ax1_0_1 < 3; ++ax1_0_1) {

  {
    unsigned int addr;
#if TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST
    addr = static_cast<unsigned int>(__cvta_generic_to_shared((void *)((&(B_decode_reindex_shared[(((((((int)threadIdx.z) * 1536) + (ax1_0_1 * 512)) + ((((int)threadIdx.x) >> 4) * 256)) + ((((int)threadIdx.x) & 7) * 32)) + ((((ax3_0_1 * 2) + ((((int)threadIdx.x) & 15) >> 3)) ^ ((((int)threadIdx.x) & 7) >> 1)) * 8))])) + 0)));
#else
    __asm__ __volatile__(
      "{ .reg .u64 addr; cvta.to.shared.u64 addr, %1; cvt.u32.u64 %0, addr; }\n"
      : "=r"(addr)
      : "l"((void *)((&(B_decode_reindex_shared[(((((((int)threadIdx.z) * 1536) + (ax1_0_1 * 512)) + ((((int)threadIdx.x) >> 4) * 256)) + ((((int)threadIdx.x) & 7) * 32)) + ((((ax3_0_1 * 2) + ((((int)threadIdx.x) & 15) >> 3)) ^ ((((int)threadIdx.x) & 7) >> 1)) * 8))])) + 0))
    );
#endif
    __asm__ __volatile__(
      "ldmatrix.sync.aligned.m8n8.x4.shared.b16"
      "{%0, %1, %2, %3}, [%4];\n"
      : "=r"(((unsigned *)(B_decode_reindex_shared_warp + (ax1_0_1 * 8)))[0]), "=r"(((unsigned *)(B_decode_reindex_shared_warp + (ax1_0_1 * 8)))[1]), "=r"(((unsigned *)(B_decode_reindex_shared_warp + (ax1_0_1 * 8)))[2]), "=r"(((unsigned *)(B_decode_reindex_shared_warp + (ax1_0_1 * 8)))[3])
      : "r"(addr)
    );
  }
        }
        for (int ax1_0_3 = 0; ax1_0_3 < 2; ++ax1_0_3) {
          for (int ax2_0_3 = 0; ax2_0_3 < 3; ++ax2_0_3) {

  {
    __asm__ __volatile__(
      "mma.sync.aligned.m16n8k16.row.col.f16.f16.f16.f16"
      "{%0, %1}, {%2, %3, %4, %5}, {%6, %7}, {%8, %9};\n"
      :  "=r"(((unsigned *)(C_reindex_shared_warp + ((ax1_0_3 * 24) + (ax2_0_3 * 8))))[0]), "=r"(((unsigned *)(C_reindex_shared_warp + ((ax1_0_3 * 24) + (ax2_0_3 * 8))))[1])
      : "r"(((unsigned *)(A_reindex_shared_warp + (ax1_0_3 * 8)))[0]), "r"(((unsigned *)(A_reindex_shared_warp + (ax1_0_3 * 8)))[1]), "r"(((unsigned *)(A_reindex_shared_warp + (ax1_0_3 * 8)))[2]), "r"(((unsigned *)(A_reindex_shared_warp + (ax1_0_3 * 8)))[3]), "r"(((unsigned *)(B_decode_reindex_shared_warp + (ax2_0_3 * 8)))[0]), "r"(((unsigned *)(B_decode_reindex_shared_warp + (ax2_0_3 * 8)))[1]), "r"(((unsigned *)(C_reindex_shared_warp + ((ax1_0_3 * 24) + (ax2_0_3 * 8))))[0]), "r"(((unsigned *)(C_reindex_shared_warp + ((ax1_0_3 * 24) + (ax2_0_3 * 8))))[1]));
  }

  {
    __asm__ __volatile__(
      "mma.sync.aligned.m16n8k16.row.col.f16.f16.f16.f16"
      "{%0, %1}, {%2, %3, %4, %5}, {%6, %7}, {%8, %9};\n"
      :  "=r"(((unsigned *)(C_reindex_shared_warp + (((ax1_0_3 * 24) + (ax2_0_3 * 8)) + 4)))[0]), "=r"(((unsigned *)(C_reindex_shared_warp + (((ax1_0_3 * 24) + (ax2_0_3 * 8)) + 4)))[1])
      : "r"(((unsigned *)(A_reindex_shared_warp + (ax1_0_3 * 8)))[0]), "r"(((unsigned *)(A_reindex_shared_warp + (ax1_0_3 * 8)))[1]), "r"(((unsigned *)(A_reindex_shared_warp + (ax1_0_3 * 8)))[2]), "r"(((unsigned *)(A_reindex_shared_warp + (ax1_0_3 * 8)))[3]), "r"(((unsigned *)(B_decode_reindex_shared_warp + ((ax2_0_3 * 8) + 4)))[0]), "r"(((unsigned *)(B_decode_reindex_shared_warp + ((ax2_0_3 * 8) + 4)))[1]), "r"(((unsigned *)(C_reindex_shared_warp + (((ax1_0_3 * 24) + (ax2_0_3 * 8)) + 4)))[0]), "r"(((unsigned *)(C_reindex_shared_warp + (((ax1_0_3 * 24) + (ax2_0_3 * 8)) + 4)))[1]));
  }
          }
        }
      }
    }
__asm__ __volatile__("cp.async.wait_group 0;");

    __syncthreads();
    for (int ax1_ax2_0_fused_0_1 = 0; ax1_ax2_0_fused_0_1 < 3; ++ax1_ax2_0_fused_0_1) {
      B_local_1[0] = *(int*)(B_shared + (((((ax1_ax2_0_fused_0_1 * 512) + (((int)threadIdx.y) * 256)) + (((int)threadIdx.z) * 128)) + (((int)threadIdx.x) * 4)) + 2048));
      decode_i4s_to_f16_scale(B_local_1, B_decode_reindex_local_1, (&(Scale[((((((((int)blockIdx.x) * 3840) + (ax1_ax2_0_fused_0_1 * 1280)) + (((int)threadIdx.y) * 640)) + (((int)threadIdx.z) * 320)) + ((((int)threadIdx.x) >> 2) * 40)) + 39)])), 8);
      *(uint4*)(B_decode_reindex_shared + (((((ax1_ax2_0_fused_0_1 * 1024) + (((int)threadIdx.y) * 512)) + (((int)threadIdx.z) * 256)) + ((((int)threadIdx.x) >> 2) * 32)) + (((((int)threadIdx.x) & 3) ^ (((int)threadIdx.x) >> 3)) * 8))) = B_decode_reindex_local_1[0];
    }
    __syncthreads();
    for (int ax3_0_1_1 = 0; ax3_0_1_1 < 2; ++ax3_0_1_1) {
      for (int ax1_0_2 = 0; ax1_0_2 < 2; ++ax1_0_2) {

  {
    unsigned int addr;
#if TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST
    addr = static_cast<unsigned int>(__cvta_generic_to_shared((void *)((&(A_reindex_shared[(((((((int)threadIdx.y) * 1024) + (ax1_0_2 * 512)) + ((((int)threadIdx.x) & 15) * 32)) + ((((ax3_0_1_1 * 2) + (((int)threadIdx.x) >> 4)) ^ ((((int)threadIdx.x) & 7) >> 1)) * 8)) + 2048)])) + 0)));
#else
    __asm__ __volatile__(
      "{ .reg .u64 addr; cvta.to.shared.u64 addr, %1; cvt.u32.u64 %0, addr; }\n"
      : "=r"(addr)
      : "l"((void *)((&(A_reindex_shared[(((((((int)threadIdx.y) * 1024) + (ax1_0_2 * 512)) + ((((int)threadIdx.x) & 15) * 32)) + ((((ax3_0_1_1 * 2) + (((int)threadIdx.x) >> 4)) ^ ((((int)threadIdx.x) & 7) >> 1)) * 8)) + 2048)])) + 0))
    );
#endif
    __asm__ __volatile__(
      "ldmatrix.sync.aligned.m8n8.x4.shared.b16"
      "{%0, %1, %2, %3}, [%4];\n"
      : "=r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_2 * 8)))[0]), "=r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_2 * 8)))[1]), "=r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_2 * 8)))[2]), "=r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_2 * 8)))[3])
      : "r"(addr)
    );
  }
      }
      for (int ax1_0_4 = 0; ax1_0_4 < 3; ++ax1_0_4) {

  {
    unsigned int addr;
#if TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST
    addr = static_cast<unsigned int>(__cvta_generic_to_shared((void *)((&(B_decode_reindex_shared[(((((((int)threadIdx.z) * 1536) + (ax1_0_4 * 512)) + ((((int)threadIdx.x) >> 4) * 256)) + ((((int)threadIdx.x) & 7) * 32)) + ((((ax3_0_1_1 * 2) + ((((int)threadIdx.x) & 15) >> 3)) ^ ((((int)threadIdx.x) & 7) >> 1)) * 8))])) + 0)));
#else
    __asm__ __volatile__(
      "{ .reg .u64 addr; cvta.to.shared.u64 addr, %1; cvt.u32.u64 %0, addr; }\n"
      : "=r"(addr)
      : "l"((void *)((&(B_decode_reindex_shared[(((((((int)threadIdx.z) * 1536) + (ax1_0_4 * 512)) + ((((int)threadIdx.x) >> 4) * 256)) + ((((int)threadIdx.x) & 7) * 32)) + ((((ax3_0_1_1 * 2) + ((((int)threadIdx.x) & 15) >> 3)) ^ ((((int)threadIdx.x) & 7) >> 1)) * 8))])) + 0))
    );
#endif
    __asm__ __volatile__(
      "ldmatrix.sync.aligned.m8n8.x4.shared.b16"
      "{%0, %1, %2, %3}, [%4];\n"
      : "=r"(((unsigned *)(B_decode_reindex_shared_warp_1 + (ax1_0_4 * 8)))[0]), "=r"(((unsigned *)(B_decode_reindex_shared_warp_1 + (ax1_0_4 * 8)))[1]), "=r"(((unsigned *)(B_decode_reindex_shared_warp_1 + (ax1_0_4 * 8)))[2]), "=r"(((unsigned *)(B_decode_reindex_shared_warp_1 + (ax1_0_4 * 8)))[3])
      : "r"(addr)
    );
  }
      }
      for (int ax1_0_3_1 = 0; ax1_0_3_1 < 2; ++ax1_0_3_1) {
        for (int ax2_0_3_1 = 0; ax2_0_3_1 < 3; ++ax2_0_3_1) {

  {
    __asm__ __volatile__(
      "mma.sync.aligned.m16n8k16.row.col.f16.f16.f16.f16"
      "{%0, %1}, {%2, %3, %4, %5}, {%6, %7}, {%8, %9};\n"
      :  "=r"(((unsigned *)(C_reindex_shared_warp + ((ax1_0_3_1 * 24) + (ax2_0_3_1 * 8))))[0]), "=r"(((unsigned *)(C_reindex_shared_warp + ((ax1_0_3_1 * 24) + (ax2_0_3_1 * 8))))[1])
      : "r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_3_1 * 8)))[0]), "r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_3_1 * 8)))[1]), "r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_3_1 * 8)))[2]), "r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_3_1 * 8)))[3]), "r"(((unsigned *)(B_decode_reindex_shared_warp_1 + (ax2_0_3_1 * 8)))[0]), "r"(((unsigned *)(B_decode_reindex_shared_warp_1 + (ax2_0_3_1 * 8)))[1]), "r"(((unsigned *)(C_reindex_shared_warp + ((ax1_0_3_1 * 24) + (ax2_0_3_1 * 8))))[0]), "r"(((unsigned *)(C_reindex_shared_warp + ((ax1_0_3_1 * 24) + (ax2_0_3_1 * 8))))[1]));
  }

  {
    __asm__ __volatile__(
      "mma.sync.aligned.m16n8k16.row.col.f16.f16.f16.f16"
      "{%0, %1}, {%2, %3, %4, %5}, {%6, %7}, {%8, %9};\n"
      :  "=r"(((unsigned *)(C_reindex_shared_warp + (((ax1_0_3_1 * 24) + (ax2_0_3_1 * 8)) + 4)))[0]), "=r"(((unsigned *)(C_reindex_shared_warp + (((ax1_0_3_1 * 24) + (ax2_0_3_1 * 8)) + 4)))[1])
      : "r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_3_1 * 8)))[0]), "r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_3_1 * 8)))[1]), "r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_3_1 * 8)))[2]), "r"(((unsigned *)(A_reindex_shared_warp_1 + (ax1_0_3_1 * 8)))[3]), "r"(((unsigned *)(B_decode_reindex_shared_warp_1 + ((ax2_0_3_1 * 8) + 4)))[0]), "r"(((unsigned *)(B_decode_reindex_shared_warp_1 + ((ax2_0_3_1 * 8) + 4)))[1]), "r"(((unsigned *)(C_reindex_shared_warp + (((ax1_0_3_1 * 24) + (ax2_0_3_1 * 8)) + 4)))[0]), "r"(((unsigned *)(C_reindex_shared_warp + (((ax1_0_3_1 * 24) + (ax2_0_3_1 * 8)) + 4)))[1]));
  }
        }
      }
    }
    for (int ax0 = 0; ax0 < 2; ++ax0) {
      for (int ax1 = 0; ax1 < 3; ++ax1) {
        __syncthreads();
        for (int local_id = 0; local_id < 8; local_id+=2) {
*((uint *)&(&(B_decode_reindex_shared[((((int)threadIdx.y) * 2048) + (((int)threadIdx.z) * 768))]))[((((((local_id % 4) / 2) * 8) + (threadIdx.x / 4)) * 16) + ((((local_id / 4) * 8) + ((threadIdx.x % 4) * 2)) + (local_id % 2)))]) = *((uint *)&C_reindex_shared_warp[((ax0 * 24) + (ax1 * 8)) + local_id]);
}
;
        __syncthreads();
        #pragma unroll
        for (int ax0_ax1_ax2_ax3_ax4_fused_0 = 0; ax0_ax1_ax2_ax3_ax4_fused_0 < 1; ++ax0_ax1_ax2_ax3_ax4_fused_0) {
          *(uint4*)(D + ((((((((((int)blockIdx.y) * 983040) + (((int)threadIdx.y) * 491520)) + (ax0 * 245760)) + ((((int)threadIdx.x) >> 1) * 15360)) + (((int)blockIdx.x) * 96)) + (((int)threadIdx.z) * 48)) + (ax1 * 16)) + ((((int)threadIdx.x) & 1) * 8))) = *(uint4*)(B_decode_reindex_shared + (((((int)threadIdx.y) * 2048) + (((int)threadIdx.z) * 768)) + (((int)threadIdx.x) * 8)));
        }
      }
    }
  }
}





int ladder_gemm_fp16xint2_fp16(half *input_0, half *input_1, half *output, const int M, const int N, const int K, const int trans_a, const int trans_b, half *workspace_ptr)
{
    assert(trans_a == 0 && trans_b == 1);
    
    if (M == 1 && N == 15360 && K == 5120){
        
             const dim3 GridDim(7680, 1, 1);
             const dim3 BlockDim(64, 2, 1);
             bitblas_kernel_fp16_int2_fp16_m1n15360k5120_nt<<<GridDim, BlockDim>>>(input_0, input_1, output);
        
        return 0;
    }

    
    if (M == 128 && N == 15360 && K == 5120){
        
             const dim3 GridDim(160, 2, 1);
             const dim3 BlockDim(1, 2, 2);
             bitblas_kernel_fp16_int2_fp16_m128n15360k5120_nt<<<GridDim, BlockDim>>>(input_0, input_1, output);
        
        return 0;
    }

    
    return -1;
}