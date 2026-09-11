/* Typed launch inputs for the existing fingerprint seed fields. */
#pragma once

#include "json.hpp"
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace camoufox {

class FingerprintSeeds {
 public:
  static FingerprintSeeds Resolve(const nlohmann::json& config) {
    FingerprintSeeds result;
    if (!config.is_object()) return result;
    result.Read(config, "canvas:seed", result.mCanvas);
    result.Read(config, "audio:seed", result.mAudio);
    result.Read(config, "fonts:spacing_seed", result.mFonts);
    return result;
  }

  const auto& Errors() const { return mErrors; }
  std::optional<uint32_t> Canvas() const { return mCanvas; }
  std::optional<uint32_t> Audio() const { return mAudio; }
  std::optional<uint32_t> Fonts() const { return mFonts; }

 private:
  std::optional<uint32_t> mCanvas;
  std::optional<uint32_t> mAudio;
  std::optional<uint32_t> mFonts;
  std::vector<std::string> mErrors;

  void Read(const nlohmann::json& config, const char* key,
            std::optional<uint32_t>& output) {
    const auto it = config.find(key);
    if (it == config.end()) return;
    if (!it->is_number_integer() ||
        (it->is_number_unsigned() ? it->get<uint64_t>() > UINT32_MAX
                                  : it->get<int64_t>() < 0 ||
                                        it->get<int64_t>() > UINT32_MAX)) {
      mErrors.emplace_back(std::string(key) +
          " must be an integer between 0 and 4294967295");
      return;
    }
    output = it->get<uint32_t>();
  }
};

}  // namespace camoufox
