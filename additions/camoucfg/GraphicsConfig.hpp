/* Startup graphics policy and portable WebGPU profile validation. */
#pragma once

#include "json.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <initializer_list>
#include <set>
#include <string>
#include <string_view>
#include <vector>

namespace camoufox {

struct AdapterProfile {
  nlohmann::json values = nlohmann::json::object();
  bool forceFallbackAdapter = false;
};

class GraphicsConfig {
 public:
  using Json = nlohmann::json;
  inline static constexpr std::string_view FeatureNames[] = {
      "core-features-and-limits", "depth-clip-control",
      "depth32float-stencil8", "texture-compression-bc",
      "texture-compression-bc-sliced-3d", "texture-compression-etc2",
      "texture-compression-astc", "texture-compression-astc-sliced-3d",
      "timestamp-query", "indirect-first-instance", "shader-f16",
      "rg11b10ufloat-renderable", "bgra8unorm-storage",
      "float32-filterable", "float32-blendable", "clip-distances",
      "dual-source-blending", "subgroups", "primitive-index"};
  inline static constexpr std::string_view WgslFeatureNames[] = {
      "packed_4x8_integer_dot_product", "pointer_composite_access",
      "readonly_and_readwrite_storage_textures"};
  inline static constexpr std::string_view LimitNames[] = {
      "maxTextureDimension1D", "maxTextureDimension2D",
      "maxTextureDimension3D", "maxTextureArrayLayers", "maxBindGroups",
      "maxBindGroupsPlusVertexBuffers", "maxBindingsPerBindGroup",
      "maxDynamicUniformBuffersPerPipelineLayout",
      "maxDynamicStorageBuffersPerPipelineLayout",
      "maxSampledTexturesPerShaderStage", "maxSamplersPerShaderStage",
      "maxStorageBuffersInVertexStage", "maxStorageBuffersInFragmentStage",
      "maxStorageBuffersPerShaderStage", "maxStorageTexturesInVertexStage",
      "maxStorageTexturesInFragmentStage", "maxStorageTexturesPerShaderStage",
      "maxUniformBuffersPerShaderStage", "maxUniformBufferBindingSize",
      "maxStorageBufferBindingSize", "minUniformBufferOffsetAlignment",
      "minStorageBufferOffsetAlignment", "maxVertexBuffers", "maxBufferSize",
      "maxVertexAttributes", "maxVertexBufferArrayStride",
      "maxInterStageShaderVariables", "maxColorAttachments",
      "maxColorAttachmentBytesPerSample", "maxComputeWorkgroupStorageSize",
      "maxComputeInvocationsPerWorkgroup", "maxComputeWorkgroupSizeX",
      "maxComputeWorkgroupSizeY", "maxComputeWorkgroupSizeZ",
      "maxComputeWorkgroupsPerDimension"};

  static GraphicsConfig Resolve(const Json& config) {
    GraphicsConfig out;
    if (!config.is_object()) return out;
    for (const auto key : {"gfx:hardwareAcceleration", "webgpu:enabled"}) {
      if (!config.contains(key)) continue;
      if (!config[key].is_boolean()) {
        out.Error(key, "must be boolean");
      } else if (std::string_view(key) == "webgpu:enabled") {
        out.mWebGPU = config[key].get<bool>();
      } else {
        out.mAcceleration = config[key].get<bool>();
      }
    }
    if (!config.contains("webgpu:profile")) return out;
    auto profile = config["webgpu:profile"];
    const std::string path = "webgpu:profile";
    if (!out.Object(profile, path, {"gpu", "adapter", "adapterOverrides"}))
      return out;
    if (profile.contains("gpu")) {
      auto& gpu = profile["gpu"];
      if (out.Object(gpu, path + ".gpu",
                     {"wgslLanguageFeatures", "preferredCanvasFormat"})) {
        if (gpu.contains("wgslLanguageFeatures"))
          out.StringSet(gpu["wgslLanguageFeatures"],
                        path + ".gpu.wgslLanguageFeatures", WgslFeatureNames);
        if (gpu.contains("preferredCanvasFormat") &&
            gpu["preferredCanvasFormat"] != "rgba8unorm" &&
            gpu["preferredCanvasFormat"] != "bgra8unorm")
          out.Error(path + ".gpu.preferredCanvasFormat",
                    "must be rgba8unorm or bgra8unorm");
      }
    }
    if (profile.contains("adapter"))
      out.ValidateAdapter(profile["adapter"], path + ".adapter");
    if (profile.contains("adapterOverrides")) {
      auto& overrides = profile["adapterOverrides"];
      if (!overrides.is_array()) {
        out.Error(path + ".adapterOverrides", "must be an array");
      } else {
        for (size_t i = 0; i < overrides.size(); ++i) {
          auto& item = overrides[i];
          const auto itemPath = path + ".adapterOverrides[" +
                                std::to_string(i) + "]";
          if (!out.Object(item, itemPath, {"request", "adapter"})) continue;
          if (!item.contains("request") || !item.contains("adapter")) {
            out.Error(itemPath, "requires request and adapter");
            continue;
          }
          out.ValidateAdapter(item["adapter"], itemPath + ".adapter");
          auto& request = item["request"];
          if (!out.Object(request, itemPath + ".request",
                          {"powerPreference", "forceFallbackAdapter",
                           "featureLevel", "xrCompatible"})) continue;
          if (request.empty()) out.Error(itemPath + ".request", "must not be empty");
          for (const auto key : {"forceFallbackAdapter", "xrCompatible"})
            if (request.contains(key) && !request[key].is_boolean())
              out.Error(itemPath + ".request." + key, "must be boolean");
          if (request.contains("powerPreference") &&
              request["powerPreference"] != "low-power" &&
              request["powerPreference"] != "high-performance")
            out.Error(itemPath + ".request.powerPreference",
                      "must be low-power or high-performance");
          if (request.contains("featureLevel") && request["featureLevel"] != "core" &&
              request["featureLevel"] != "compatibility")
            out.Error(itemPath + ".request.featureLevel",
                      "must be core or compatibility");
          for (size_t j = 0; j < i; ++j) {
            const auto& other = overrides[j];
            if (!other.is_object() || !other.contains("request") ||
                !other["request"].is_object()) continue;
            const auto& previous = other["request"];
            if (previous.size() != request.size()) continue;
            bool overlap = true;
            for (auto it = request.begin(); it != request.end(); ++it)
              if (previous.contains(it.key()) && previous[it.key()] != it.value())
                overlap = false;
            if (overlap) out.Error(itemPath + ".request",
                "ambiguous with adapterOverrides[" + std::to_string(j) + "]");
          }
        }
      }
    }
    if (out.mErrors.empty()) out.mProfile = std::move(profile);
    return out;
  }

  bool HardwareAcceleration() const { return mAcceleration; }
  bool WebGPUEnabled() const { return mWebGPU; }
  const std::vector<std::string>& Errors() const { return mErrors; }
  const Json& GPU() const {
    static const Json empty = Json::object();
    return mProfile.contains("gpu") ? mProfile["gpu"] : empty;
  }
  AdapterProfile SelectAdapter(const Json& request) const {
    AdapterProfile result;
    result.forceFallbackAdapter = request.value("forceFallbackAdapter", false);
    if (mProfile.contains("adapter")) result.values = mProfile["adapter"];
    const Json* selected = nullptr;
    size_t specificity = 0;
    if (mProfile.contains("adapterOverrides")) {
      for (const auto& entry : mProfile["adapterOverrides"]) {
        const auto& conditions = entry["request"];
        bool matches = true;
        for (auto it = conditions.begin(); it != conditions.end(); ++it)
          if (!request.contains(it.key()) || request[it.key()] != it.value())
            matches = false;
        if (matches && conditions.size() > specificity) {
          selected = &entry["adapter"];
          specificity = conditions.size();
        }
      }
    }
    if (selected) {
      for (auto it = selected->begin(); it != selected->end(); ++it) {
        if (it.key() == "features") {
          result.values[it.key()] = it.value();
        } else {
          if (!result.values.contains(it.key())) result.values[it.key()] = Json::object();
          result.values[it.key()].update(it.value());
        }
      }
    }
    return result;
  }

 private:
  bool mAcceleration = false;
  bool mWebGPU = false;
  Json mProfile = Json::object();
  std::vector<std::string> mErrors;
  void Error(const std::string& path, const std::string& reason) {
    mErrors.push_back(path + ": " + reason);
  }
  bool Object(const Json& object, const std::string& path,
              std::initializer_list<std::string_view> allowed) {
    if (!object.is_object()) { Error(path, "must be an object"); return false; }
    for (auto it = object.begin(); it != object.end(); ++it)
      if (std::find(allowed.begin(), allowed.end(), it.key()) == allowed.end())
        Error(path + "." + it.key(), "unknown field");
    return true;
  }
  template <size_t N>
  void StringSet(Json& value, const std::string& path,
                 const std::string_view (&allowed)[N]) {
    if (!value.is_array()) { Error(path, "must be an array"); return; }
    std::set<std::string> names;
    for (size_t i = 0; i < value.size(); ++i) {
      if (!value[i].is_string()) {
        Error(path + "[" + std::to_string(i) + "]", "must be a string");
        continue;
      }
      auto name = value[i].get<std::string>();
      if (std::find(std::begin(allowed), std::end(allowed), name) == std::end(allowed))
        Error(path + "[" + std::to_string(i) + "]", "unknown or unimplemented feature " + name);
      names.insert(std::move(name));
    }
    value = names;
  }
  void Unsigned(Json& value, const std::string& path, uint64_t maximum) {
    if (!value.is_number() || !std::isfinite(value.get<double>()) ||
        value.get<double>() < 0 || value.get<double>() > static_cast<double>(maximum) ||
        std::floor(value.get<double>()) != value.get<double>()) {
      Error(path, "must be an unsigned integer <= " + std::to_string(maximum));
      return;
    }
    value = value.get<uint64_t>();
  }
  void ValidateAdapter(Json& adapter, const std::string& path) {
    if (!Object(adapter, path, {"info", "features", "limits"})) return;
    if (adapter.contains("info")) {
      auto& info = adapter["info"];
      if (Object(info, path + ".info", {"vendor", "architecture", "device",
          "description", "subgroupMinSize", "subgroupMaxSize", "isFallbackAdapter"})) {
        for (const auto key : {"vendor", "architecture", "device", "description"})
          if (info.contains(key) && !info[key].is_string())
            Error(path + ".info." + key, "must be a string");
        if (info.contains("isFallbackAdapter") && !info["isFallbackAdapter"].is_boolean())
          Error(path + ".info.isFallbackAdapter", "must be boolean");
        for (const auto key : {"subgroupMinSize", "subgroupMaxSize"})
          if (info.contains(key)) Unsigned(info[key], path + ".info." + key, UINT32_MAX);
      }
    }
    if (adapter.contains("features"))
      StringSet(adapter["features"], path + ".features", FeatureNames);
    if (adapter.contains("limits")) {
      auto& limits = adapter["limits"];
      if (!limits.is_object()) { Error(path + ".limits", "must be an object"); return; }
      for (auto it = limits.begin(); it != limits.end(); ++it) {
        if (std::find(std::begin(LimitNames), std::end(LimitNames), it.key()) == std::end(LimitNames)) {
          Error(path + ".limits." + it.key(), "unknown limit");
          continue;
        }
        const bool wide = it.key() == "maxBufferSize" ||
                          it.key() == "maxUniformBufferBindingSize" ||
                          it.key() == "maxStorageBufferBindingSize";
        Unsigned(it.value(), path + ".limits." + it.key(),
                 wide ? 9007199254740991ULL : UINT32_MAX);
      }
    }
  }
};

}  // namespace camoufox
