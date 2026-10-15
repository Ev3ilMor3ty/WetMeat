#include "evaluate.hpp"

#include <algorithm>
#include <bit>
#include <cmath>

namespace aurora {

namespace {
constexpr std::array<int, 8> passed_mg{{0, 0, 6, 14, 28, 48, 80, 0}};
constexpr std::array<int, 8> passed_eg{{0, 4, 12, 28, 52, 90, 150, 0}};
constexpr Bitboard dark_squares = 0xaa55aa55aa55aa55ULL;
int distance(int a, int b) {
    return std::max(std::abs(file_of(a) - file_of(b)), std::abs(rank_of(a) - rank_of(b)));
}
Bitboard neighbor_files(int file) {
    return (file > 0 ? file_masks[file - 1] : 0) | (file < 7 ? file_masks[file + 1] : 0);
}
} // namespace

Evaluator::Evaluator() : pawn_table(std::make_unique<PawnEntry[]>(PAWN_ENTRIES)) {}
void Evaluator::clear() {
    for (std::size_t i = 0; i < PAWN_ENTRIES; ++i) pawn_table[i].valid = false;
}

const PawnEntry& Evaluator::pawns(const Position& position) {
    PawnEntry& entry = pawn_table[position.pawn_key & (PAWN_ENTRIES - 1)];
    if (entry.valid && entry.key == position.pawn_key) return entry;
    entry = PawnEntry{};
    entry.valid = true;
    entry.key = position.pawn_key;
    for (Color color : {WHITE, BLACK}) {
        Bitboard ours = position.pieces[color][PAWN];
        Bitboard theirs = position.pieces[opposite(color)][PAWN];
        Bitboard pending = ours;
        while (pending) {
            int square = pop_lsb(pending), file = file_of(square), rank = relative_rank(color, square);
            entry.attacks[color] |= pawn_attacks[color][square];
            bool isolated = !(ours & neighbor_files(file));
            bool protected_pawn = pawn_attacks[opposite(color)][square] & ours;
            bool connected = protected_pawn;
            if (file > 0 && (ours & bit(square - 1))) connected = true;
            if (file < 7 && (ours & bit(square + 1))) connected = true;
            if (isolated) { entry.mg[color] -= 13; entry.eg[color] -= 17; }
            if (connected) { entry.mg[color] += 3 + 2 * rank; entry.eg[color] += 3 * rank; }
            if (!(passed_masks[color][square] & theirs)) {
                entry.passed[color] |= bit(square);
                entry.mg[color] += passed_mg[rank];
                entry.eg[color] += passed_eg[rank];
            }
            // A pawn with no neighbor behind it and an enemy-controlled advance is backward.
            int ahead = square + (color == WHITE ? 8 : -8);
            Bitboard supporters = neighbor_files(file) & ours & ~passed_masks[color][square];
            if (!isolated && !supporters && (pawn_attacks[color][ahead] & theirs)) {
                entry.mg[color] -= 10;
                entry.eg[color] -= 8;
            }
        }
        for (int file = 0; file < 8; ++file) {
            int count = std::popcount(ours & file_masks[file]);
            if (count > 1) {
                entry.mg[color] -= (count - 1) * 11;
                entry.eg[color] -= (count - 1) * 18;
            }
        }
    }
    return entry;
}

int Evaluator::evaluate(const Position& position) {
    const PawnEntry& pawn_entry = pawns(position);
    auto mg = position.mg;
    auto eg = position.eg;
    Bitboard occupancy = position.occupied();
    std::array<Bitboard, 2> attack_maps = pawn_entry.attacks;
    std::array<int, 2> king_attackers{};
    std::array<int, 2> king_pressure{};
    constexpr std::array<int, 6> attack_weights{{1, 2, 2, 3, 5, 0}};

    for (Color color : {WHITE, BLACK}) {
        Color enemy = opposite(color);
        mg[color] += pawn_entry.mg[color];
        eg[color] += pawn_entry.eg[color];
        if (std::popcount(position.pieces[color][BISHOP]) >= 2) { mg[color] += 30; eg[color] += 44; }
        Bitboard mobility_area = ~position.colors[color] & ~pawn_entry.attacks[enemy];
        Bitboard king_zone = king_attacks[position.kings[enemy]] | bit(position.kings[enemy]);

        for (PieceType type : {KNIGHT, BISHOP, ROOK, QUEEN}) {
            Bitboard pending = position.pieces[color][type];
            while (pending) {
                int square = pop_lsb(pending);
                Bitboard attacks = type == KNIGHT ? knight_attacks[square]
                    : type == BISHOP ? bishop_attacks(square, occupancy)
                    : type == ROOK ? rook_attacks(square, occupancy) : queen_attacks(square, occupancy);
                attack_maps[color] |= attacks;
                int mobility = std::popcount(attacks & mobility_area);
                if (type == KNIGHT) { mg[color] += 4 * (mobility - 4); eg[color] += 4 * (mobility - 4); }
                if (type == BISHOP) { mg[color] += 4 * (mobility - 6); eg[color] += 5 * (mobility - 6); }
                if (type == ROOK) { mg[color] += 2 * (mobility - 7); eg[color] += 4 * (mobility - 7); }
                if (type == QUEEN) { mg[color] += mobility - 12; eg[color] += 2 * (mobility - 12); }
                int hits = std::popcount(attacks & king_zone);
                if (hits) {
                    ++king_attackers[color];
                    king_pressure[color] += hits * attack_weights[type];
                }
                int rank = relative_rank(color, square), file = file_of(square);
                if (type == KNIGHT && rank >= 3 && rank <= 5
                    && (pawn_entry.attacks[color] & bit(square))
                    && !(passed_masks[color][square] & neighbor_files(file) & position.pieces[enemy][PAWN])) {
                    mg[color] += 22;
                    eg[color] += 12;
                }
                if (type == BISHOP) {
                    Bitboard same_color = bit(square) & dark_squares ? dark_squares : ~dark_squares;
                    mg[color] -= 2 * std::popcount(position.pieces[color][PAWN] & same_color);
                }
                if (type == ROOK) {
                    Bitboard file_board = file_masks[file];
                    if (!(file_board & position.pieces[color][PAWN])) {
                        bool open = !(file_board & position.pieces[enemy][PAWN]);
                        mg[color] += open ? 24 : 12;
                        eg[color] += open ? 14 : 8;
                    }
                    if (rank == 6 && (relative_rank(color, position.kings[enemy]) == 7
                        || (position.pieces[enemy][PAWN] & (color == WHITE ? 0x00ff000000000000ULL : 0x000000000000ff00ULL)))) {
                        mg[color] += 18;
                        eg[color] += 26;
                    }
                }
            }
        }
        attack_maps[color] |= king_attacks[position.kings[color]];
        Bitboard passed = pawn_entry.passed[color];
        while (passed) {
            int square = pop_lsb(passed), rank = relative_rank(color, square);
            int ahead = square + (color == WHITE ? 8 : -8);
            if (!position.board[ahead]) { mg[color] += rank * 2; eg[color] += rank * 4; }
            else { mg[color] -= rank * 3; eg[color] -= rank * 5; }
            eg[color] += rank * (distance(position.kings[enemy], ahead) - distance(position.kings[color], ahead)) * 3;
        }
    }

    for (Color color : {WHITE, BLACK}) {
        Color enemy = opposite(color);
        int king = position.kings[color], file = file_of(king), rank = rank_of(king);
        int shelter = 0;
        for (int nf = std::max(0, file - 1); nf <= std::min(7, file + 1); ++nf) {
            Bitboard our_pawns = file_masks[nf] & position.pieces[color][PAWN];
            int near = 8;
            while (our_pawns) {
                int square = pop_lsb(our_pawns);
                int advance = (rank_of(square) - rank) * (color == WHITE ? 1 : -1);
                if (advance > 0) near = std::min(near, advance);
            }
            shelter += near == 1 ? 12 : near == 2 ? 3 : -14;
            if (!(file_masks[nf] & (position.pieces[WHITE][PAWN] | position.pieces[BLACK][PAWN]))) shelter -= 10;
        }
        mg[color] += shelter;
        if (king_attackers[enemy] >= 2) {
            int pressure = king_pressure[enemy];
            int weak = std::popcount(king_attacks[king] & attack_maps[enemy] & ~attack_maps[color]);
            int danger = std::min(480, pressure * pressure / 2 + 12 * weak);
            if (!position.pieces[enemy][QUEEN]) danger /= 2;
            mg[color] -= danger;
        }
        Bitboard threatened = position.colors[color] & ~position.pieces[color][KING] & pawn_entry.attacks[enemy];
        while (threatened) {
            int square = pop_lsb(threatened);
            if (type_of(position.board[square]) != PAWN) { mg[color] -= 22; eg[color] -= 14; }
        }
    }
    int phase = std::clamp(position.phase, 0, 24);
    int score = ((mg[WHITE] - mg[BLACK]) * phase + (eg[WHITE] - eg[BLACK]) * (24 - phase)) / 24;
    // Modest scaling in opposite-colored bishop endgames.
    if (!position.pieces[WHITE][QUEEN] && !position.pieces[BLACK][QUEEN]
        && !position.pieces[WHITE][ROOK] && !position.pieces[BLACK][ROOK]
        && !position.pieces[WHITE][KNIGHT] && !position.pieces[BLACK][KNIGHT]
        && std::popcount(position.pieces[WHITE][BISHOP]) == 1 && std::popcount(position.pieces[BLACK][BISHOP]) == 1
        && bool(position.pieces[WHITE][BISHOP] & dark_squares) != bool(position.pieces[BLACK][BISHOP] & dark_squares))
        score = score * 3 / 4;
    score = score * (100 - std::clamp(position.halfmove - 20, 0, 80)) / 100;
    return std::clamp((position.side == WHITE ? score : -score) + 12, -28000, 28000);
}

} // namespace aurora
