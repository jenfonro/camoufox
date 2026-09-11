/* Deterministic sample-indexed audio perturbation shared by readback paths. */
#pragma once
#include <cstdint>

namespace camoufox {

inline uint32_t AudioSeedState(uint32_t seed, uint32_t offset) {
  uint32_t multiplier = 1664525u, increment = 1013904223u;
  uint32_t accumulatedMultiplier = 1, accumulatedIncrement = 0;
  while (offset) {
    if (offset & 1) {
      accumulatedMultiplier *= multiplier;
      accumulatedIncrement = accumulatedIncrement * multiplier + increment;
    }
    increment *= multiplier + 1;
    multiplier *= multiplier;
    offset >>= 1;
  }
  return accumulatedMultiplier * seed + accumulatedIncrement;
}

inline float AudioSeedMultiplier(uint32_t& state) {
  state = state * 1664525u + 1013904223u;
  const float normalized = static_cast<float>(state) / 4294967295.0f;
  const float base = 0.996f + normalized * 0.008f;
  const float adjustment = (normalized * normalized - 0.5f) * 0.002f;
  return base + adjustment;
}

}  // namespace camoufox
