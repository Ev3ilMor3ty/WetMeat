#pragma once

#include "chess.hpp"

#include <array>
#include <string_view>

namespace aurora::neural {

constexpr int KING_BUCKETS = 8;
constexpr int FEATURES = KING_BUCKETS * 12 * 64;
constexpr int HIDDEN = 64;
constexpr int CACHE_SLOTS = 128;
constexpr int FEATURE_SCALE = 256;
constexpr int OUTPUT_SCALE = 1024;
constexpr int CORRECTION_LIMIT = 400;

bool available();
std::string_view model_id();

class Network {
public:
    int correction(const Position& position);
    void clear();

private:
    struct Mapping {
        int bucket = 0;
        int transform = 0;
        bool operator==(const Mapping&) const = default;
    };
    struct Frame {
        std::uint64_t key = 0;
        bool valid = false;
        std::array<Mapping, 2> mapping{};
        std::array<std::array<std::int32_t, HIDDEN>, 2> accumulator{};
    };
    std::array<Frame, CACHE_SLOTS> cache{};
    static Mapping mapping(const Position& position, Color perspective);
    static int feature(int p, int square, Color perspective, Mapping map);
    static void change(Frame& frame, Color perspective, int p, int square, int sign);
    static void refresh(Frame& frame, Color perspective, const Position& position);
    Frame& prepare(const Position& position);
};

} // namespace aurora::neural
