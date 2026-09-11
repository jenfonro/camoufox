#include "FingerprintSeeds.hpp"
#include "AudioSeed.hpp"
#include <cassert>
#include <iostream>

int main() {
  using json = nlohmann::json;
  const auto native = camoufox::FingerprintSeeds::Resolve(json::object());
  assert(native.Errors().empty() && !native.Canvas());
  for (const auto key : {"canvas:seed", "audio:seed", "fonts:spacing_seed"}) {
    for (const auto& bad : json::array({true, -1, 4294967296ULL, "123", nullptr, 1.0}))
      assert(!camoufox::FingerprintSeeds::Resolve({{key, bad}}).Errors().empty());
    assert(camoufox::FingerprintSeeds::Resolve({{key, 0}}).Errors().empty());
    assert(camoufox::FingerprintSeeds::Resolve({{key, 4294967295ULL}}).Errors().empty());
  }
  const auto zero = camoufox::FingerprintSeeds::Resolve({{"canvas:seed", 0}});
  assert(zero.Canvas().has_value() && zero.Canvas().value() == 0);
  for (const uint32_t seed : {1u, 12345u, UINT32_MAX}) {
    uint32_t sequential = seed;
    for (uint32_t i = 0; i < 2000; ++i) {
      assert(camoufox::AudioSeedState(seed, i) == sequential);
      auto offset = camoufox::AudioSeedState(seed, i);
      assert(camoufox::AudioSeedMultiplier(offset) == camoufox::AudioSeedMultiplier(sequential));
    }
    assert(camoufox::AudioSeedState(camoufox::AudioSeedState(seed, 123456), 987654) ==
           camoufox::AudioSeedState(seed, 1111110));
  }
  std::cout << "fingerprint seed validation and indexed audio transformations passed\n";
}
