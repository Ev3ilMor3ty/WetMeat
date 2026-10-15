#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace aurora {

using Bitboard = std::uint64_t;
using Move = std::uint32_t;

enum Color : int { WHITE, BLACK };
enum PieceType : int { PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING, NO_TYPE };
constexpr Color opposite(Color color) { return Color(color ^ 1); }
constexpr int piece(Color color, PieceType type) { return 1 + int(type) + 6 * int(color); }
constexpr Color color_of(int p) { return Color((p - 1) / 6); }
constexpr PieceType type_of(int p) { return PieceType((p - 1) % 6); }
constexpr Bitboard bit(int square) { return Bitboard(1) << square; }
constexpr int file_of(int square) { return square & 7; }
constexpr int rank_of(int square) { return square >> 3; }
constexpr int relative_rank(Color color, int square) { return rank_of(square) ^ (color == BLACK ? 7 : 0); }

constexpr Move CAPTURE = 1u << 15;
constexpr Move EN_PASSANT = 1u << 16;
constexpr Move CASTLING = 1u << 17;
constexpr Move DOUBLE_PUSH = 1u << 18;
constexpr Move NO_MOVE = 0;
constexpr Move move_of(int from, int to, Move flags = 0, PieceType promotion = PAWN) {
    return Move(from | (to << 6) | (int(promotion) << 12)) | flags;
}
constexpr int from_sq(Move move) { return move & 63; }
constexpr int to_sq(Move move) { return (move >> 6) & 63; }
constexpr PieceType promotion_of(Move move) { return PieceType((move >> 12) & 7); }
constexpr bool is_capture(Move move) { return move & CAPTURE; }
constexpr bool is_promotion(Move move) { return promotion_of(move) != PAWN; }
constexpr bool is_quiet(Move move) { return !is_capture(move) && !is_promotion(move); }

struct MoveList {
    std::array<Move, 256> moves{};
    int size = 0;
    void add(Move move) { moves[size++] = move; }
    Move* begin() { return moves.data(); }
    Move* end() { return moves.data() + size; }
    const Move* begin() const { return moves.data(); }
    const Move* end() const { return moves.data() + size; }
};

extern std::array<Bitboard, 64> knight_attacks;
extern std::array<Bitboard, 64> king_attacks;
extern std::array<std::array<Bitboard, 64>, 2> pawn_attacks;
extern std::array<Bitboard, 8> file_masks;
extern std::array<std::array<Bitboard, 64>, 2> passed_masks;
extern std::array<std::array<int, 64>, 6> mg_table;
extern std::array<std::array<int, 64>, 6> eg_table;
extern const std::array<int, 6> material_values;
extern const std::array<int, 6> phase_values;

void init_chess();
int pop_lsb(Bitboard& board);
Bitboard bishop_attacks(int square, Bitboard occupied);
Bitboard rook_attacks(int square, Bitboard occupied);
inline Bitboard queen_attacks(int square, Bitboard occupied) {
    return bishop_attacks(square, occupied) | rook_attacks(square, occupied);
}
std::string square_name(int square);
std::string move_name(Move move);

struct Undo {
    Move move = NO_MOVE;
    int captured = 0;
    int rights = 0;
    int ep = -1;
    int halfmove = 0;
    int fullmove = 1;
    std::uint64_t key = 0;
    std::uint64_t pawn_key = 0;
    std::array<int, 2> mg{};
    std::array<int, 2> eg{};
    int phase = 0;
};

class Position {
public:
    static constexpr std::string_view START_FEN =
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

    Position();
    bool set_fen(std::string_view fen, std::string& error);
    std::string fen() const;
    void generate(MoveList& moves, bool tactical_only = false) const;
    MoveList legal_moves();
    Move parse_move(std::string_view text);
    bool make(Move move); // On an illegal move, restores the original position.
    void unmake();
    void make_null();
    void unmake_null();
    bool in_check() const { return attacked(kings[side], opposite(side)); }
    bool attacked(int square, Color by) const;
    Bitboard attackers_to(int square, Color by, Bitboard occupancy, Bitboard removed = 0) const;
    bool repetition(int search_ply = 0) const;
    bool insufficient_material() const;
    bool drawn(int search_ply = 0);
    bool has_legal_move();
    int see(Move move) const;
    bool consistent() const;
    std::uint64_t recompute_key() const;

    std::array<int, 64> board{};
    std::array<std::array<Bitboard, 6>, 2> pieces{};
    std::array<Bitboard, 2> colors{};
    std::array<int, 2> kings{{-1, -1}};
    Color side = WHITE;
    int rights = 0; // White king/queen side: 1/2, black: 4/8.
    int ep = -1;
    int halfmove = 0;
    int fullmove = 1;
    std::uint64_t key = 0;
    std::uint64_t pawn_key = 0;
    std::array<int, 2> mg{};
    std::array<int, 2> eg{};
    int phase = 0;
    std::vector<Undo> history;
    Bitboard occupied() const { return colors[WHITE] | colors[BLACK]; }
    Bitboard non_pawn_material(Color color) const {
        return colors[color] & ~(pieces[color][PAWN] | pieces[color][KING]);
    }

private:
    explicit Position(bool empty);
    void put(int square, int p);
    void remove(int square);
    int hashable_ep_file() const;
    Undo save(Move move) const;
    void restore(const Undo& undo);
};

std::uint64_t perft(Position& position, int depth);

} // namespace aurora
