#pragma once

#include "chess.hpp"

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
    Evaluator();
    int evaluate(const Position& position);
    void clear();

private:
    static constexpr std::size_t PAWN_ENTRIES = 16384;
    std::unique_ptr<PawnEntry[]> pawn_table;
    const PawnEntry& pawns(const Position& position);
};

} // namespace aurora
