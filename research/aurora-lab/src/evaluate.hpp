#pragma once

#include "chess.hpp"
#include "neural.hpp"

#include <array>
#include <memory>

namespace aurora {

struct PawnEntry {
    std::uint64_t key = 0;
    bool valid = false;
    std::array<int, 2> mg{};
    std::array<int, 2> eg{};
    std::array<Bitboard, 2> passed{};
    std::array<Bitboard, 2> attacks{};
};

class Evaluator {
public:
    explicit Evaluator(int neural_weight = -1);
    int evaluate(const Position& position);
    void clear();

private:
    static constexpr std::size_t PAWN_ENTRIES = 16384;
    std::unique_ptr<PawnEntry[]> pawn_table;
    neural::Network network;
    int neural_weight;
    const PawnEntry& pawns(const Position& position);
};

} // namespace aurora
