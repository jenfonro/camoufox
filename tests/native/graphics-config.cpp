#include "GraphicsConfig.hpp"
#include <cassert>
#include <iostream>

using camoufox::GraphicsConfig;
using json = nlohmann::json;

int main() {
  const auto defaults = GraphicsConfig::Resolve(json::object());
  assert(defaults.Errors().empty());
  assert(!defaults.HardwareAcceleration() && !defaults.WebGPUEnabled());
  const auto enabled = GraphicsConfig::Resolve({{"gfx:hardwareAcceleration", true},
                                                 {"webgpu:enabled", true}});
  assert(enabled.Errors().empty() && enabled.HardwareAcceleration() && enabled.WebGPUEnabled());
  assert(!GraphicsConfig::Resolve({{"webgpu:enabled", 1}}).Errors().empty());
  assert(!GraphicsConfig::Resolve({{"webgpu:profile", nullptr}}).Errors().empty());

  auto config = json::parse(R"({
    "webgpu:profile": {
      "adapter": {
        "info": {"vendor": "base", "description": "", "isFallbackAdapter": false},
        "features": ["timestamp-query", "core-features-and-limits", "timestamp-query"],
        "limits": {"maxBufferSize": 4294967296, "maxBindGroups": 4}
      },
      "adapterOverrides": [
        {"request": {"forceFallbackAdapter": true},
         "adapter": {"info": {"isFallbackAdapter": true}, "features": []}},
        {"request": {"forceFallbackAdapter": true, "powerPreference": "high-performance"},
         "adapter": {"info": {"vendor": "specific", "isFallbackAdapter": true}}}
      ]
    }
  })");
  const json ordinary = {{"featureLevel", "core"}, {"forceFallbackAdapter", false}, {"xrCompatible", false}};
  auto policy = GraphicsConfig::Resolve(config);
  assert(policy.Errors().empty());
  auto selected = policy.SelectAdapter(ordinary);
  assert(selected.values["info"]["vendor"] == "base");
  assert(selected.values["info"]["description"] == "");
  assert(selected.values["limits"]["maxBufferSize"].get<uint64_t>() == 4294967296ULL);
  assert(selected.values["features"] == json({"core-features-and-limits", "timestamp-query"}));
  auto fallback = ordinary; fallback["forceFallbackAdapter"] = true;
  selected = policy.SelectAdapter(fallback);
  assert(selected.forceFallbackAdapter && selected.values["features"].empty());
  assert(selected.values["info"]["vendor"] == "base");
  assert(selected.values["info"]["isFallbackAdapter"] == true);
  fallback["powerPreference"] = "high-performance";
  selected = policy.SelectAdapter(fallback);
  assert(selected.values["info"]["vendor"] == "specific");
  assert(selected.values["features"].size() == 2);
  std::reverse(config["webgpu:profile"]["adapterOverrides"].begin(),
               config["webgpu:profile"]["adapterOverrides"].end());
  assert(GraphicsConfig::Resolve(config).SelectAdapter(fallback).values == selected.values);

  auto bad = config;
  bad["webgpu:profile"]["adapter"]["limits"]["maxBindGroups"] = true;
  assert(!GraphicsConfig::Resolve(bad).Errors().empty());
  bad = config; bad["webgpu:profile"]["adapter"]["limits"]["maxBufferSize"] = 9007199254740992ULL;
  assert(!GraphicsConfig::Resolve(bad).Errors().empty());
  bad = config; bad["webgpu:profile"]["adapter"]["features"] = {"unknown"};
  assert(!GraphicsConfig::Resolve(bad).Errors().empty());
  bad = config; bad["webgpu:profile"]["adapter"]["info"]["renderer"] = "not-webgpu";
  assert(!GraphicsConfig::Resolve(bad).Errors().empty());
  bad = config;
  bad["webgpu:profile"]["adapterOverrides"] = json::parse(R"([
    {"request":{"powerPreference":"high-performance"},"adapter":{}},
    {"request":{"forceFallbackAdapter":true},"adapter":{}}
  ])");
  assert(!GraphicsConfig::Resolve(bad).Errors().empty());
  assert(!GraphicsConfig::Resolve({{"webgpu:profile", {{"adapterOverrides", {true}}}}}).Errors().empty());
  std::cout << "graphics-config native contract checks passed\n";
}
