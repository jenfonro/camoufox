/* Resolution overrides shared by browser startup and content-facing APIs. */
#pragma once

#include "json.hpp"
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace camoufox {

class WindowResolution {
 public:
  enum class Mode { Native, Global, Profile };

  static constexpr std::array<std::string_view, 17> Properties = {
      "screen.width", "screen.height",
      "screen.availWidth", "screen.availHeight",
      "screen.availLeft", "screen.availTop",
      "window.outerWidth", "window.outerHeight",
      "window.innerWidth", "window.innerHeight",
      "window.screenX", "window.screenY", "window.devicePixelRatio",
      "document.body.clientWidth", "document.body.clientHeight",
      "document.body.clientLeft", "document.body.clientTop"};

  static WindowResolution Resolve(const nlohmann::json& config) {
    WindowResolution result;
    if (!config.is_object()) {
      return result;
    }

    if (auto policy = config.find("window:mode"); policy != config.end()) {
      if (!policy->is_string() ||
          (*policy != "auto" && *policy != "native")) {
        result.mExplicitNative = true;
        result.mErrors.emplace_back(
            "window:mode must be 'auto' or 'native'; using native geometry");
        return result;
      }
      if (*policy == "native") {
        result.mExplicitNative = true;
        return result;
      }
    }

    const nlohmann::json* values = nullptr;
    for (auto key : Properties) {
      if (config.contains(std::string(key))) {
        result.mMode = Mode::Global;
        values = &config;
        break;
      }
    }

    // A legacy/global override wins as a whole. Do not mix dimensions from
    // two different identities when both inputs are supplied.
    if (!values) {
      auto profile = config.find("window:profile");
      if (profile == config.end()) {
        return result;
      }
      if (!profile->is_object()) {
        result.mErrors.emplace_back("window:profile must be an object");
        return result;
      }
      values = &*profile;
      if (!values->empty()) {
        result.mMode = Mode::Profile;
      }
    }

    for (auto key : Properties) {
      auto item = values->find(std::string(key));
      if (item == values->end()) {
        continue;
      }
      const bool floating = key == "window.devicePixelRatio" ||
                            key == "window.innerWidth" ||
                            key == "window.innerHeight";
      if (!item->is_number() || (!floating && !item->is_number_integer())) {
        result.mErrors.emplace_back(std::string(key) + " must be numeric");
        continue;
      }
      const double value = item->get<double>();
      const bool positive = key == "screen.width" || key == "screen.height" ||
                            key == "window.outerWidth" ||
                            key == "window.outerHeight" ||
                            key == "window.innerWidth" ||
                            key == "window.innerHeight" ||
                            key == "window.devicePixelRatio";
      const bool nonnegative = key == "screen.availWidth" ||
                               key == "screen.availHeight" ||
                               key == "document.body.clientWidth" ||
                               key == "document.body.clientHeight";
      if (!std::isfinite(value) ||
          value < std::numeric_limits<int32_t>::min() ||
          value > std::numeric_limits<int32_t>::max() ||
          (positive && value <= 0) || (nonnegative && value < 0)) {
        result.mErrors.emplace_back(std::string(key) + " is out of range");
        continue;
      }
      result.mValues[std::string(key)] = *item;
    }
    if (result.mMode == Mode::Profile &&
        result.mValues.contains("screen.width") &&
        result.mValues.contains("screen.height") &&
        !result.mValues.contains("screen.availWidth") &&
        !result.mValues.contains("screen.availHeight")) {
      result.mValues["screen.availWidth"] = result.mValues["screen.width"];
      result.mValues["screen.availHeight"] = result.mValues["screen.height"];
    }
    return result;
  }

  Mode GetMode() const { return mMode; }

  const char* ModeName() const {
    switch (mMode) {
      case Mode::Global: return "global";
      case Mode::Profile: return "profile";
      default: return "native";
    }
  }

  // Preserve the existing per-context screen API, including callers that do
  // not provide any process-wide geometry. An explicit native opt-out also
  // suppresses those overrides. Browser chrome always measures real geometry;
  // global overrides resize it explicitly during startup.
  bool AllowsContextOverrides(bool content) const {
    return !mExplicitNative && content;
  }

  std::optional<double> GlobalNumber(std::string_view key) const {
    return mMode == Mode::Global ? Number(key, true) : std::nullopt;
  }

  std::optional<int32_t> Int(std::string_view key, bool content) const {
    const auto* value = Find(key, content);
    if (!value || !value->is_number_integer()) {
      return std::nullopt;
    }
    return value->get<int32_t>();
  }

  std::optional<double> Number(std::string_view key, bool content) const {
    const auto* value = Find(key, content);
    return value ? std::optional<double>(value->get<double>()) : std::nullopt;
  }

  std::optional<std::array<int32_t, 4>> Rect(
      std::string_view left, std::string_view top, std::string_view width,
      std::string_view height, bool content) const {
    const auto w = Int(width, content);
    const auto h = Int(height, content);
    if (!w || !h) {
      return std::nullopt;
    }
    return std::array<int32_t, 4>{Int(left, content).value_or(0),
                                  Int(top, content).value_or(0), *w, *h};
  }

  const std::vector<std::string>& Errors() const { return mErrors; }

 private:
  const nlohmann::json* Find(std::string_view key, bool content) const {
    if (mMode == Mode::Native || !content) {
      return nullptr;
    }
    const auto it = mValues.find(std::string(key));
    return it == mValues.end() ? nullptr : &*it;
  }

  Mode mMode = Mode::Native;
  bool mExplicitNative = false;
  nlohmann::json mValues = nlohmann::json::object();
  std::vector<std::string> mErrors;
};

}  // namespace camoufox
