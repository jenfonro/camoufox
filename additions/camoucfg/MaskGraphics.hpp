#pragma once
#include "GraphicsConfig.hpp"
#include "MaskConfig.hpp"

namespace MaskConfig {
inline const camoufox::GraphicsConfig& GetGraphicsConfig() {
  static const auto config = camoufox::GraphicsConfig::Resolve(GetJson());
  return config;
}
}  // namespace MaskConfig
