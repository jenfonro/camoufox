#pragma once
#include "FingerprintSeeds.hpp"
#include "MaskConfig.hpp"

namespace MaskConfig {
inline const camoufox::FingerprintSeeds& GetFingerprintSeeds() {
  static const auto seeds = camoufox::FingerprintSeeds::Resolve(GetJson());
  return seeds;
}
}  // namespace MaskConfig
