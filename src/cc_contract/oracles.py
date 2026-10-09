"""Independent mathematical float references; no tolerance fitted to GPU output."""
import math
import struct

FLOAT32_U = 2.0 ** -24


def float32(value):
    return struct.unpack('f', struct.pack('f', value))[0]


def dot_reference(left, right):
    if len(left) != len(right) or not left:
        raise ValueError('Dot operands must have equal nonempty shapes')
    # Inputs are first rounded to the actual device input format. Products and
    # the reference sum use Python binary64, independently of torch/CUDA.
    products = [float32(a) * float32(b) for a, b in zip(left, right)]
    return math.fsum(products), math.fsum(abs(p) for p in products)


def dot_verdict(observed, left, right, bias=0.0):
    reference, magnitude = dot_reference(left, right)
    bias = float32(bias)
    reference += bias
    magnitude += abs(bias)
    n = 2 * len(left) + 2  # conservative separate multiply/add rounding bound
    if not math.isfinite(observed) or not math.isfinite(reference):
        return {'verdict': 'INCONCLUSIVE', 'reason': 'nonfinite_value'}
    if n * FLOAT32_U >= 1 or any(0 < abs(float32(v)) < 2 ** -126 for v in left + right):
        return {'verdict': 'INCONCLUSIVE', 'reason': 'rounding_model_preconditions_not_met'}
    gamma = n * FLOAT32_U / (1 - n * FLOAT32_U)
    # Includes conservative binary64 reference rounding and float32 underflow.
    bound = gamma * magnitude + n * 2 ** -149 + n * 2 ** -52 * magnitude
    error = abs(observed - reference)
    return {'verdict': 'PASS' if error <= bound else 'FAIL', 'reference': reference,
            'absolute_error': error, 'bound': bound, 'rule': 'gamma_2n_plus_2_sum_abs_products_float32',
            'preconditions': 'float32 operands, TF32 off, no subnormal inputs, finite output'}


def paired_logits(reference, observed):
    """Diagnostic pair comparison, not an independent model-correctness oracle.

    Identical model arithmetic and dtype are required. A divergence is a
    candidate anomaly until repeated and localized; similarity alone is not
    proof that both executions are mathematically correct.
    """
    if len(reference) != len(observed) or not reference:
        return {'verdict': 'INVALID_TEST', 'reason': 'shape_mismatch'}
    if not all(math.isfinite(v) for v in reference + observed):
        return {'verdict': 'INCONCLUSIVE', 'reason': 'nonfinite_logits'}
    return {'verdict': 'PASS' if reference == observed else 'INCONCLUSIVE',
            'exact_equal': reference == observed,
            'maximum_absolute_difference': max(abs(a-b) for a,b in zip(reference,observed)),
            'reason': 'paired_diagnostic_requires_independent_component_oracles'}
