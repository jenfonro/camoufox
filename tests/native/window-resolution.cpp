#include "WindowResolution.hpp"
#include <cassert>
#include <iostream>

using camoufox::WindowResolution;
using json = nlohmann::json;
using Mode = WindowResolution::Mode;

int main() {
  auto native = WindowResolution::Resolve(json::object());
  assert(native.GetMode() == Mode::Native);
  assert(!native.Int("screen.width", true));
  assert(!native.GlobalNumber("window.outerWidth"));
  assert(native.AllowsContextOverrides(true));
  assert(!native.AllowsContextOverrides(false));

  const json portrait = {{"screen.width", 1920}, {"screen.height", 1080},
                         {"window.innerWidth", 1400}, {"window.innerHeight", 800},
                         {"window.screenX", -200}, {"window.devicePixelRatio", 1.5}};
  auto profile = WindowResolution::Resolve({{"window:profile", portrait}});
  assert(profile.GetMode() == Mode::Profile);
  assert(profile.Int("screen.width", true) == 1920);
  assert(profile.Int("screen.availWidth", true) == 1920);
  assert(profile.Int("window.screenX", true) == -200);
  assert(profile.Number("window.devicePixelRatio", true) == 1.5);
  assert(!profile.Int("screen.width", false));
  assert(!profile.Number("window.innerWidth", false));
  assert(!profile.GlobalNumber("window.innerWidth"));
  auto rect = profile.Rect("screen.availLeft", "screen.availTop",
                           "screen.availWidth", "screen.availHeight", true);
  assert(rect && (*rect)[0] == 0 && (*rect)[2] == 1920 && (*rect)[3] == 1080);

  // Legacy/global input wins as a whole and still supplies real resize requests.
  auto global = WindowResolution::Resolve({{"window.outerWidth", 1100},
                                           {"window:profile", portrait}});
  assert(global.GetMode() == Mode::Global);
  assert(global.Int("window.outerWidth", true) == 1100);
  assert(global.GlobalNumber("window.outerWidth") == 1100);
  assert(!global.Int("screen.width", true));
  assert(!global.Int("window.outerWidth", false));

  auto optOut = WindowResolution::Resolve({{"window:mode", "native"},
                                           {"window.outerWidth", 1100},
                                           {"window:profile", portrait}});
  assert(optOut.GetMode() == Mode::Native);
  assert(!optOut.Int("window.outerWidth", true));
  assert(!optOut.AllowsContextOverrides(true));

  // Unrelated fingerprint properties must not select global geometry.
  auto unrelated = WindowResolution::Resolve({{"navigator.platform", "Win32"},
                                               {"window.history.length", 3},
                                               {"window:profile", portrait}});
  assert(unrelated.GetMode() == Mode::Profile);

  auto invalid = WindowResolution::Resolve({{"window:profile", {
      {"screen.width", true}, {"screen.height", -1},
      {"window.outerWidth", 4294967295ULL}, {"window.devicePixelRatio", 0}}}});
  assert(!invalid.Int("screen.width", true));
  assert(!invalid.Int("screen.height", true));
  assert(!invalid.Int("window.outerWidth", true));
  assert(!invalid.Number("window.devicePixelRatio", true));
  assert(invalid.Errors().size() == 4);

  auto zero = WindowResolution::Resolve({{"window:profile", {
      {"screen.availWidth", 0}, {"screen.availHeight", 0},
      {"document.body.clientWidth", 0}, {"document.body.clientHeight", 0}}}});
  assert(zero.Int("screen.availWidth", true) == 0);
  assert(zero.Int("document.body.clientWidth", true) == 0);
  assert(zero.Errors().empty());

  std::cout << "window resolution policy checks passed\n";
}
