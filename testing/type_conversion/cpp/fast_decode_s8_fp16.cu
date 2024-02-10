#include <stdio.h>
#include <cuda_runtime.h>
#if defined(__CUDA_ARCH__) && (__CUDA_ARCH__ >= 530)
#include <cuda_fp16.h>
__device__ half max(half a, half b)
{
  return __hgt(__half(a), __half(b)) ? a : b;
}
__device__ half min(half a, half b)
{
  return __hlt(__half(a), __half(b)) ? a : b;
}
#else

typedef unsigned short uint16_t;
typedef unsigned char uint8_t;
typedef signed char int8_t;
typedef int int32_t;
typedef unsigned long long uint64_t;
typedef unsigned int uint;

#define TVM_FORCE_INLINE inline __attribute__((always_inline))
#define TVM_XINLINE TVM_FORCE_INLINE __device__ __host__
#define TVM_ALIGNED(x) __attribute__((aligned(x)))
#define TVM_HALF_OPERATOR(RTYPE, OP)            \
  TVM_XINLINE RTYPE operator OP(half a, half b) \
  {                                             \
    return RTYPE(float(a) OP float(b));         \
  }                                             \
  template <typename T>                         \
  TVM_XINLINE RTYPE operator OP(half a, T b)    \
  {                                             \
    return RTYPE(float(a) OP float(b));         \
  }                                             \
  template <typename T>                         \
  TVM_XINLINE RTYPE operator OP(T a, half b)    \
  {                                             \
    return RTYPE(float(a) OP float(b));         \
  }

#define TVM_HALF_ASSIGNOP(AOP, OP)                            \
  template <typename T>                                       \
  TVM_XINLINE half operator AOP(const T &a)                   \
  {                                                           \
    return *this = half(float(*this) OP float(a));            \
  }                                                           \
  template <typename T>                                       \
  TVM_XINLINE half operator AOP(const volatile T &a) volatile \
  {                                                           \
    return *this = half(float(*this) OP float(a));            \
  }

class TVM_ALIGNED(2) half
{
public:
  uint16_t half_;

  static TVM_XINLINE half Binary(uint16_t value)
  {
    half res;
    res.half_ = value;
    return res;
  }

  TVM_XINLINE half() {}

  TVM_XINLINE half(const float &value) { constructor(value); }
  TVM_XINLINE explicit half(const double &value) { constructor(value); }
  TVM_XINLINE explicit half(const int8_t &value) { constructor(value); }
  TVM_XINLINE explicit half(const uint8_t &value) { constructor(value); }
  TVM_XINLINE explicit half(const int32_t &value) { constructor(value); }
  TVM_XINLINE explicit half(const uint &value) { constructor(value); }
  TVM_XINLINE explicit half(const long long &value) { constructor(value); }
  TVM_XINLINE explicit half(const uint64_t &value) { constructor(value); }

  TVM_XINLINE operator float() const
  {
    return float(half2float(half_));
  }
  TVM_XINLINE operator float() const volatile
  {
    return float(half2float(half_));
  }

  TVM_HALF_ASSIGNOP(+=, +)
  TVM_HALF_ASSIGNOP(-=, -)
  TVM_HALF_ASSIGNOP(*=, *)
  TVM_HALF_ASSIGNOP(/=, /)

  TVM_XINLINE half operator+()
  {
    return *this;
  }

  TVM_XINLINE half operator-()
  {
    return half(-float(*this));
  }

  TVM_XINLINE half operator=(const half &a)
  {
    half_ = a.half_;
    return a;
  }

  template <typename T>
  TVM_XINLINE half operator=(const T &a)
  {
    return *this = half(a);
  }

  TVM_XINLINE half operator=(const half &a) volatile
  {
    half_ = a.half_;
    return a;
  }

  template <typename T>
  TVM_XINLINE half operator=(const T &a) volatile
  {
    return *this = half(a);
  }

private:
  union Bits
  {
    float f;
    int32_t si;
    uint ui;
  };

  static int const fp16FractionBits = 10;
  static int const fp32FractionBits = 23;
  static int32_t const fp32FractionMask = ~(~0u << fp32FractionBits); // == 0x7fffff
  static int32_t const fp32HiddenBit = 1 << fp32FractionBits;         // == 0x800000
  static int const shift = fp32FractionBits - fp16FractionBits;       // == 13
  static int const shiftSign = 16;
  static int32_t const expAdjust = 127 - 15; // exp32-127 = exp16-15, so exp16 = exp32 - (127-15)

  static int32_t const infN = 0x7F800000;  // flt32 infinity
  static int32_t const maxN = 0x477FFFFF;  // max flt32 that's a flt16 normal after >> by shift
  static int32_t const minN = 0x38800000;  // min flt16 normal as a flt32
  static int32_t const maxZ = 0x33000000;  // max fp32 number that's still rounded to zero in fp16
  static int32_t const signN = 0x80000000; // flt32 sign bit

  static int32_t const infC = infN >> shift;
  static int32_t const nanN = (infC + 1) << shift; // minimum flt16 nan as a flt32
  static int32_t const maxC = maxN >> shift;
  static int32_t const minC = minN >> shift;
  static int32_t const signC = signN >> shiftSign; // flt16 sign bit

  static int32_t const mulN = 0x52000000; // (1 << 23) / minN
  static int32_t const mulC = 0x33800000; // minN / (1 << (23 - shift))

  static int32_t const subC = 0x003FF; // max flt32 subnormal down shifted
  static int32_t const norC = 0x00400; // min flt32 normal down shifted

  static int32_t const maxD = infC - maxC - 1;
  static int32_t const minD = minC - subC - 1;

  TVM_XINLINE uint16_t float2half(const float &value) const
  {
    Bits v;
    v.f = value;
    uint sign = v.si & signN; // grab sign bit
    v.si ^= sign;                 // clear sign bit from v
    sign >>= shiftSign;           // logical shift sign to fp16 position

    if (v.si <= maxZ)
    {
      // Handle eventual zeros here to ensure
      // vshift will not exceed 32 below.
      v.ui = 0;
    }
    else if (v.si < minN)
    {
      // Handle denorms
      uint exp32 = v.ui >> fp32FractionBits;
      int32_t exp16 = exp32 - expAdjust;
      // If exp16 == 0 (just into the denorm range), then significant should be shifted right 1.
      // Smaller (so negative) exp16 values should result in greater right shifts.
      uint vshift = 1 - exp16;
      uint significand = fp32HiddenBit | (v.ui & fp32FractionMask);
      v.ui = significand >> vshift;
      v.ui += (v.ui & 0x3fff) != 0x1000 || (significand & 0x7ff) ? 0x1000 : 0;
    }
    else if (v.si <= maxN)
    {
      // Handle norms
      v.ui += (v.ui & 0x3fff) != 0x1000 ? 0x1000 : 0;
      v.ui -= expAdjust << fp32FractionBits;
    }
    else if (v.si <= infN)
    {
      v.si = infN;
    }
    else if (v.si < nanN)
    {
      v.si = nanN;
    }

    v.ui >>= shift;
    return sign | (v.ui & 0x7fff);
  }

  // Same as above routine, except for addition of volatile keyword
  TVM_XINLINE uint16_t float2half(
      const volatile float &value) const volatile
  {
    Bits v;
    v.f = value;
    uint sign = v.si & signN; // grab sign bit
    v.si ^= sign;                 // clear sign bit from v
    sign >>= shiftSign;           // logical shift sign to fp16 position

    if (v.si <= maxZ)
    {
      // Handle eventual zeros here to ensure
      // vshift will not exceed 32 below.
      v.ui = 0;
    }
    else if (v.si < minN)
    {
      // Handle denorms
      uint exp32 = v.ui >> fp32FractionBits;
      int32_t exp16 = exp32 - expAdjust;
      // If exp16 == 0 (just into the denorm range), then significant should be shifted right 1.
      // Smaller (so negative) exp16 values should result in greater right shifts.
      uint vshift = 1 - exp16;
      uint significand = fp32HiddenBit | (v.ui & fp32FractionMask);
      v.ui = significand >> vshift;
      v.ui += (v.ui & 0x3fff) != 0x1000 || (significand & 0x7ff) ? 0x1000 : 0;
    }
    else if (v.si <= maxN)
    {
      // Handle norms
      v.ui += (v.ui & 0x3fff) != 0x1000 ? 0x1000 : 0;
      v.ui -= expAdjust << fp32FractionBits;
    }
    else if (v.si <= infN)
    {
      v.si = infN;
    }
    else if (v.si < nanN)
    {
      v.si = nanN;
    }

    v.ui >>= shift;
    return sign | (v.ui & 0x7fff);
  }

  TVM_XINLINE float half2float(const uint16_t &value) const
  {
    Bits v;
    v.ui = value;
    int32_t sign = v.si & signC;
    v.si ^= sign;
    sign <<= shiftSign;
    v.si ^= ((v.si + minD) ^ v.si) & -(v.si > subC);
    v.si ^= ((v.si + maxD) ^ v.si) & -(v.si > maxC);
    Bits s;
    s.si = mulC;
    s.f *= v.si;
    int32_t mask = -(norC > v.si);
    v.si <<= shift;
    v.si ^= (s.si ^ v.si) & mask;
    v.si |= sign;
    return v.f;
  }

  TVM_XINLINE float half2float(
      const volatile uint16_t &value) const volatile
  {
    Bits v;
    v.ui = value;
    int32_t sign = v.si & signC;
    v.si ^= sign;
    sign <<= shiftSign;
    v.si ^= ((v.si + minD) ^ v.si) & -(v.si > subC);
    v.si ^= ((v.si + maxD) ^ v.si) & -(v.si > maxC);
    Bits s;
    s.si = mulC;
    s.f *= v.si;
    int32_t mask = -(norC > v.si);
    v.si <<= shift;
    v.si ^= (s.si ^ v.si) & mask;
    v.si |= sign;
    return v.f;
  }

  template <typename T>
  TVM_XINLINE void constructor(const T &value)
  {
    half_ = float2half(float(value));
  }
};

TVM_HALF_OPERATOR(half, +)
TVM_HALF_OPERATOR(half, -)
TVM_HALF_OPERATOR(half, *)
TVM_HALF_OPERATOR(half, /)
TVM_HALF_OPERATOR(bool, >)
TVM_HALF_OPERATOR(bool, <)
TVM_HALF_OPERATOR(bool, >=)
TVM_HALF_OPERATOR(bool, <=)

TVM_XINLINE half __float2half_rn(const float a)
{
  return half(a);
}
#endif

// Pack two half values.
static inline __device__ __host__ unsigned
__pack_half2(const half x, const half y)
{
  unsigned v0 = *((unsigned short *)&x);
  unsigned v1 = *((unsigned short *)&y);
  return (v1 << 16) | v0;
}

// Some fp16 math functions are not supported in cuda_fp16.h,
// so we define them here to make sure the generated CUDA code
// is valid.
#if defined(__CUDA_ARCH__) && (__CUDA_ARCH__ >= 530)
#define CUDA_UNSUPPORTED_HALF_MATH_BINARY(HALF_MATH_NAME, FP32_MATH_NAME) \
  static inline __device__ __host__ half HALF_MATH_NAME(half x, half y)   \
  {                                                                       \
    float tmp_x = __half2float(x);                                        \
    float tmp_y = __half2float(y);                                        \
    float result = FP32_MATH_NAME(tmp_x, tmp_y);                          \
    return __float2half(result);                                          \
  }

#define CUDA_UNSUPPORTED_HALF_MATH_UNARY(HALF_MATH_NAME, FP32_MATH_NAME) \
  static inline __device__ __host__ half HALF_MATH_NAME(half x)          \
  {                                                                      \
    float tmp_x = __half2float(x);                                       \
    float result = FP32_MATH_NAME(tmp_x);                                \
    return __float2half(result);                                         \
  }

CUDA_UNSUPPORTED_HALF_MATH_BINARY(hpow, powf)
CUDA_UNSUPPORTED_HALF_MATH_UNARY(htanh, tanhf)
CUDA_UNSUPPORTED_HALF_MATH_UNARY(htan, tanf)
CUDA_UNSUPPORTED_HALF_MATH_UNARY(hatan, atanf)
CUDA_UNSUPPORTED_HALF_MATH_UNARY(herf, erf)

#undef CUDA_UNSUPPORTED_HALF_MATH_BINARY
#undef CUDA_UNSUPPORTED_HALF_MATH_UNARY

#endif
#if defined(__CUDA_ARCH__) && (__CUDA_ARCH__ >= 610)
#include <sm_61_intrinsics.h>
#endif

#if (((__CUDACC_VER_MAJOR__ == 11) && (__CUDACC_VER_MINOR__ >= 4)) || \
     (__CUDACC_VER_MAJOR__ > 11))
#define TVM_ENABLE_L2_PREFETCH 1
#else
#define TVM_ENABLE_L2_PREFETCH 0
#endif

#if defined(__CUDA_ARCH__) && (__CUDA_ARCH__ == 800)
#define TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST 1
#else
#define TVM_ENBALE_EFFICIENT_SMEM_PTR_CAST 0
#endif

#ifdef _WIN32
using uint = unsigned int;
using uchar = unsigned char;
using ushort = unsigned short;
using ushort = unsigned short;
using uint64_t = unsigned long long;
#else
#define uint unsigned int
#define uchar unsigned char
#define ushort unsigned short
#define int64_t long long
#define uint64_t unsigned long long
#endif

__device__ void decode_i8s_to_f16(int *i8s, half *B_local_decode)
{

  uint *h = reinterpret_cast<uint *>(B_local_decode);
  uint const top_i8s = *i8s;

  // static constexpr uint mask_for_elt_01 = 0x5250;
  static constexpr uint mask_for_elt_01 = 0x5150;
  // mask_for_elt_01就是选择器，根据选择器和{b,a}，我们可以的到h[0]的值
  // mask_for_elt_01 -> [0][101] [0][010] [0][101] [0][000]
  // mask_for_elt_01 ->   d.b3     d.b2     d.b1     d.b0
  // mask_for_elt_01 ->   5        1        5        0
  // mask_for_elt_01 ->   0x64     e1       0x64     e0
  //            h[0] ->   0x64[e1]64[e0]
  // static constexpr uint mask_for_elt_23 = 0x5351;
  static constexpr uint mask_for_elt_23 = 0x5352;
  // mask_for_elt_23就是选择器，根据选择器和{b,a}，我们可以的到h[1]的值
  // mask_for_elt_23 -> [0][101] [0][011] [0][101] [0][001]
  // mask_for_elt_23 ->   d.b3     d.b2     d.b1     d.b0
  // mask_for_elt_23 ->   5        3        5        2
  // mask_for_elt_23 ->   0x64     e3       0x64     e2
  //            h[1] ->   0x64[e3]64[e2]
  static constexpr uint start_byte_for_fp16 = 0x64646464;
  asm volatile("prmt.b32 %0,%1,%2,%3;\n" : "=r"(h[0]) : "r"(top_i8s), "n"(start_byte_for_fp16), "n"(mask_for_elt_01));
  asm volatile("prmt.b32 %0,%1,%2,%3;\n" : "=r"(h[1]) : "r"(top_i8s), "n"(start_byte_for_fp16), "n"(mask_for_elt_23));

  // Lastly, we subtract 1152 from our constructed number using fp16 math to get our signed integer as fp16.
  // minus 1024.
  static constexpr uint I8s_TO_F16s_MAGIC_NUM = 0x64006400;
  asm volatile("sub.f16x2 %0, %1, %2;\n" : "=r"(h[0]) : "r"(h[0]), "r"(I8s_TO_F16s_MAGIC_NUM));
  asm volatile("sub.f16x2 %0, %1, %2;\n" : "=r"(h[1]) : "r"(h[1]), "r"(I8s_TO_F16s_MAGIC_NUM));
}

extern "C" __global__ void main_kernel0(int8_t *__restrict__ B, half *__restrict__ B_1)
{
  // print B
  printf("B[0] = %d\n", int(B[0]));
  printf("B[1] = %d\n", int(B[1]));
  printf("B[2] = %d\n", int(B[2]));
  printf("B[3] = %d\n", int(B[3]));
  decode_i8s_to_f16(reinterpret_cast<int *>(B), B_1);
  printf("B_1[0] = %f\n", float(B_1[0]));
  printf("B_1[1] = %f\n", float(B_1[1]));
  printf("B_1[2] = %f\n", float(B_1[2]));
  printf("B_1[3] = %f\n", float(B_1[3]));
}

int main()
{
  // create four int8_t values
  int8_t * i8s = new int8_t[4];
  i8s[0] = 1;
  i8s[1] = 12;
  i8s[2] = 23;
  i8s[3] = 34;
  half * B_local_decode = new half[4];
  int8_t * i8s_gpu;
  half * B_local_decode_gpu;

  cudaMalloc((void **)&i8s_gpu, 4 * sizeof(int8_t));
  cudaMalloc((void **)&B_local_decode_gpu, 4 * sizeof(half));
  cudaMemcpy(i8s_gpu, i8s, 4 * sizeof(int8_t), cudaMemcpyHostToDevice);
  cudaMemcpy(B_local_decode_gpu, B_local_decode, 4 * sizeof(half), cudaMemcpyHostToDevice);
  // print the last error
  cudaError_t cudaerr = cudaDeviceSynchronize();
  if (cudaerr != cudaSuccess)
    printf("kernel launch failed with error \"%s\".\n",
           cudaGetErrorString(cudaerr));
  main_kernel0<<<dim3(1,1,1), dim3(1,1,1)>>>(i8s_gpu, B_local_decode_gpu);
  // print error
  cudaerr = cudaDeviceSynchronize();
  if (cudaerr != cudaSuccess)
    printf("kernel launch failed with error \"%s\".\n",
           cudaGetErrorString(cudaerr));
  cudaMemcpy(B_local_decode, B_local_decode_gpu, 4 * sizeof(half), cudaMemcpyDeviceToHost);
  printf("B_local_decode[0] = %f\n", float(B_local_decode[0]));

  return 0;
}
