#include "chess.hpp"

#include <algorithm>
#include <bit>
#include <cassert>
#include <charconv>
#include <cmath>
#include <mutex>
#include <sstream>

namespace aurora {

std::array<Bitboard, 64> knight_attacks{};
std::array<Bitboard, 64> king_attacks{};
std::array<std::array<Bitboard, 64>, 2> pawn_attacks{};
std::array<Bitboard, 8> file_masks{};
std::array<std::array<Bitboard, 64>, 2> passed_masks{};
std::array<std::array<int, 64>, 6> mg_table{};
std::array<std::array<int, 64>, 6> eg_table{};
const std::array<int, 6> material_values{{100, 320, 335, 500, 950, 20000}};
const std::array<int, 6> phase_values{{0, 1, 1, 2, 4, 0}};

namespace {
std::array<std::array<Bitboard, 64>, 8> rays{};
std::array<std::array<std::uint64_t, 64>, 13> piece_keys{};
std::array<std::uint64_t, 16> rights_keys{};
std::array<std::uint64_t, 8> ep_keys{};
std::uint64_t side_key = 0;
std::once_flag init_flag;
constexpr std::array<int, 8> direction_file{{0, 0, 1, -1, 1, -1, 1, -1}};
constexpr std::array<int, 8> direction_rank{{1, -1, 0, 0, 1, 1, -1, -1}};
constexpr std::array<bool, 8> increasing{{true, false, true, false, true, true, false, false}};
constexpr std::string_view symbols = ".PNBRQKpnbrqk";

std::uint64_t random_key(std::uint64_t& state) {
    state += 0x9e3779b97f4a7c15ULL;
    auto z = state;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

Bitboard ray_attack(int square, int direction, Bitboard occupied) {
    Bitboard attacks = rays[direction][square];
    Bitboard blockers = attacks & occupied;
    if (blockers) {
        int blocker = increasing[direction] ? std::countr_zero(blockers) : 63 - std::countl_zero(blockers);
        attacks ^= rays[direction][blocker];
    }
    return attacks;
}

int castle_mask(int square) {
    switch (square) {
    case 0: return 13;
    case 4: return 12;
    case 7: return 14;
    case 56: return 7;
    case 60: return 3;
    case 63: return 11;
    default: return 15;
    }
}

bool parse_integer(const std::string& token, int& result, int minimum) {
    auto [end, ec] = std::from_chars(token.data(), token.data() + token.size(), result);
    return ec == std::errc{} && end == token.data() + token.size() && result >= minimum;
}
} // namespace

void init_chess() {
    std::call_once(init_flag, [] {
        std::uint64_t state = 0x4155524f52413236ULL;
        for (auto& squares : piece_keys)
            for (auto& value : squares) value = random_key(state);
        for (auto& value : rights_keys) value = random_key(state);
        for (auto& value : ep_keys) value = random_key(state);
        side_key = random_key(state);
        for (int square = 0; square < 64; ++square) {
            const int f = file_of(square), r = rank_of(square);
            file_masks[f] |= bit(square);
            for (int d = 0; d < 8; ++d) {
                int nf = f + direction_file[d], nr = r + direction_rank[d];
                while (nf >= 0 && nf < 8 && nr >= 0 && nr < 8) {
                    rays[d][square] |= bit(nr * 8 + nf);
                    nf += direction_file[d];
                    nr += direction_rank[d];
                }
            }
            for (int df = -2; df <= 2; ++df) {
                for (int dr = -2; dr <= 2; ++dr) {
                    int nf = f + df, nr = r + dr;
                    if (nf < 0 || nf >= 8 || nr < 0 || nr >= 8) continue;
                    if (std::abs(df) * std::abs(dr) == 2) knight_attacks[square] |= bit(nr * 8 + nf);
                    if (std::max(std::abs(df), std::abs(dr)) == 1) king_attacks[square] |= bit(nr * 8 + nf);
                }
            }
            for (Color color : {WHITE, BLACK}) {
                int direction = color == WHITE ? 1 : -1;
                for (int df : {-1, 1}) {
                    int nf = f + df, nr = r + direction;
                    if (nf >= 0 && nf < 8 && nr >= 0 && nr < 8) pawn_attacks[color][square] |= bit(nr * 8 + nf);
                }
                for (int nf = std::max(0, f - 1); nf <= std::min(7, f + 1); ++nf)
                    for (int nr = r + direction; nr >= 0 && nr < 8; nr += direction)
                        passed_masks[color][square] |= bit(nr * 8 + nf);
            }
            int distance = std::abs(2 * f - 7) + std::abs(2 * r - 7);
            int file_center = 7 - std::abs(2 * f - 7);
            mg_table[PAWN][square] = 100 + 6 * r + 2 * file_center;
            eg_table[PAWN][square] = 120 + 3 * r * r + file_center;
            mg_table[KNIGHT][square] = 320 + 28 - 5 * distance + (r >= 2 && r <= 5 ? 6 : 0);
            eg_table[KNIGHT][square] = 305 + 20 - 3 * distance;
            mg_table[BISHOP][square] = 335 + 18 - 2 * distance + 2 * r;
            eg_table[BISHOP][square] = 325 + 14 - 2 * distance;
            mg_table[ROOK][square] = 500 + 2 * r + file_center;
            eg_table[ROOK][square] = 525 + 2 * r;
            mg_table[QUEEN][square] = 950 + 6 - distance;
            eg_table[QUEEN][square] = 950 + 12 - 2 * distance;
            mg_table[KING][square] = -8 * r - 3 * file_center + (r == 0 && (f <= 2 || f >= 6) ? 24 : 0);
            eg_table[KING][square] = 32 - 4 * distance;
        }
    });
}

int pop_lsb(Bitboard& board) {
    assert(board);
    int square = std::countr_zero(board);
    board &= board - 1;
    return square;
}
Bitboard bishop_attacks(int square, Bitboard occupied) {
    return ray_attack(square, 4, occupied) | ray_attack(square, 5, occupied)
         | ray_attack(square, 6, occupied) | ray_attack(square, 7, occupied);
}
Bitboard rook_attacks(int square, Bitboard occupied) {
    return ray_attack(square, 0, occupied) | ray_attack(square, 1, occupied)
         | ray_attack(square, 2, occupied) | ray_attack(square, 3, occupied);
}
std::string square_name(int square) {
    return std::string{char('a' + file_of(square)), char('1' + rank_of(square))};
}
std::string move_name(Move move) {
    if (!move) return "0000";
    std::string name = square_name(from_sq(move)) + square_name(to_sq(move));
    if (is_promotion(move)) name += " pnbrqk"[promotion_of(move) + 1];
    return name;
}

Position::Position(bool) { init_chess(); history.reserve(512); }
Position::Position() : Position(true) {
    std::string error;
    bool ok = set_fen(START_FEN, error);
    assert(ok);
    (void)ok;
}

void Position::put(int square, int p) {
    assert(p > 0 && p <= 12 && board[square] == 0);
    Color color = color_of(p);
    PieceType type = type_of(p);
    board[square] = p;
    pieces[color][type] |= bit(square);
    colors[color] |= bit(square);
    key ^= piece_keys[p][square];
    if (type == PAWN) pawn_key ^= piece_keys[p][square];
    int oriented = square ^ (color == BLACK ? 56 : 0);
    mg[color] += mg_table[type][oriented];
    eg[color] += eg_table[type][oriented];
    phase += phase_values[type];
    if (type == KING) kings[color] = square;
}
void Position::remove(int square) {
    int p = board[square];
    assert(p);
    Color color = color_of(p);
    PieceType type = type_of(p);
    board[square] = 0;
    pieces[color][type] &= ~bit(square);
    colors[color] &= ~bit(square);
    key ^= piece_keys[p][square];
    if (type == PAWN) pawn_key ^= piece_keys[p][square];
    int oriented = square ^ (color == BLACK ? 56 : 0);
    mg[color] -= mg_table[type][oriented];
    eg[color] -= eg_table[type][oriented];
    phase -= phase_values[type];
}

bool Position::set_fen(std::string_view fen_text, std::string& error) {
    Position next(true);
    std::istringstream input{std::string(fen_text)};
    std::string layout, turn, castling, en_passant, half, full, extra;
    auto fail = [&](const char* message) { error = message; return false; };
    if (!(input >> layout >> turn >> castling >> en_passant >> half >> full) || (input >> extra))
        return fail("FEN muss genau sechs Felder enthalten");
    int rank = 7, file = 0;
    for (char symbol : layout) {
        if (symbol == '/') {
            if (file != 8 || rank == 0) return fail("Ungueltige FEN-Reihen");
            --rank;
            file = 0;
        } else if (symbol >= '1' && symbol <= '8') {
            file += symbol - '0';
            if (file > 8) return fail("Zu viele Felder in einer FEN-Reihe");
        } else {
            auto p = symbols.find(symbol);
            if (p == std::string_view::npos || p == 0 || file >= 8) return fail("Ungueltige Figur in FEN");
            if (type_of(int(p)) == PAWN && (rank == 0 || rank == 7)) return fail("Bauer auf Grundreihe");
            next.put(rank * 8 + file++, int(p));
        }
    }
    if (rank != 0 || file != 8) return fail("FEN-Brett muss acht vollstaendige Reihen enthalten");
    for (Color color : {WHITE, BLACK})
        if (std::popcount(next.pieces[color][KING]) != 1) return fail("Jede Seite braucht genau einen Koenig");
    for (Color color : {WHITE, BLACK}) {
        int pawns = std::popcount(next.pieces[color][PAWN]);
        int promotions = std::max(0, std::popcount(next.pieces[color][QUEEN]) - 1);
        for (PieceType type : {KNIGHT, BISHOP, ROOK}) promotions += std::max(0, std::popcount(next.pieces[color][type]) - 2);
        if (pawns > 8 || std::popcount(next.colors[color]) > 16 || promotions > 8 - pawns)
            return fail("Unmoegliche Figurenanzahl in FEN");
    }
    if (turn != "w" && turn != "b") return fail("Ungueltige Zugfarbe");
    next.side = turn == "w" ? WHITE : BLACK;
    if (castling != "-") {
        for (char symbol : castling) {
            auto index = std::string_view("KQkq").find(symbol);
            if (index == std::string_view::npos || (next.rights & (1 << index))) return fail("Ungueltige Rochaderechte");
            next.rights |= 1 << index;
        }
    }
    const std::array<int, 4> rook_squares{{7, 0, 63, 56}};
    for (int index = 0; index < 4; ++index) {
        if (!(next.rights & (1 << index))) continue;
        Color color = index < 2 ? WHITE : BLACK;
        if (next.board[color == WHITE ? 4 : 60] != piece(color, KING)
            || next.board[rook_squares[index]] != piece(color, ROOK))
            return fail("Rochaderecht ohne passenden Koenig und Turm");
    }
    if (en_passant != "-") {
        if (en_passant.size() != 2 || en_passant[0] < 'a' || en_passant[0] > 'h'
            || en_passant[1] != (next.side == WHITE ? '6' : '3')) return fail("Ungueltiges En-passant-Feld");
        next.ep = (en_passant[1] - '1') * 8 + en_passant[0] - 'a';
        int captured_square = next.ep + (next.side == WHITE ? -8 : 8);
        int origin_square = next.ep + (next.side == WHITE ? 8 : -8);
        if (next.board[next.ep] || next.board[origin_square]
            || next.board[captured_square] != piece(opposite(next.side), PAWN))
            return fail("En-passant-Feld passt nicht zum letzten Doppelzug");
    }
    if (!parse_integer(half, next.halfmove, 0) || !parse_integer(full, next.fullmove, 1))
        return fail("Ungueltige FEN-Zugzaehler");
    if (next.attacked(next.kings[opposite(next.side)], next.side))
        return fail("Die Seite, die zuletzt gezogen hat, steht im Schach");
    next.key = next.recompute_key();
    *this = std::move(next);
    error.clear();
    return true;
}

std::string Position::fen() const {
    std::ostringstream output;
    for (int rank = 7; rank >= 0; --rank) {
        int empty = 0;
        for (int file = 0; file < 8; ++file) {
            int p = board[rank * 8 + file];
            if (!p) ++empty;
            else {
                if (empty) { output << empty; empty = 0; }
                output << symbols[p];
            }
        }
        if (empty) output << empty;
        if (rank) output << '/';
    }
    output << (side == WHITE ? " w " : " b ");
    if (!rights) output << '-';
    else for (int index = 0; index < 4; ++index) if (rights & (1 << index)) output << "KQkq"[index];
    output << ' ' << (ep < 0 ? "-" : square_name(ep)) << ' ' << halfmove << ' ' << fullmove;
    return output.str();
}

Bitboard Position::attackers_to(int square, Color by, Bitboard occupancy, Bitboard removed) const {
    return ((pawn_attacks[opposite(by)][square] & pieces[by][PAWN])
          | (knight_attacks[square] & pieces[by][KNIGHT])
          | (king_attacks[square] & pieces[by][KING])
          | (bishop_attacks(square, occupancy) & (pieces[by][BISHOP] | pieces[by][QUEEN]))
          | (rook_attacks(square, occupancy) & (pieces[by][ROOK] | pieces[by][QUEEN]))) & ~removed & occupancy;
}
bool Position::attacked(int square, Color by) const {
    return attackers_to(square, by, occupied()) != 0;
}
int Position::hashable_ep_file() const {
    if (ep < 0) return -1;
    Bitboard candidates = pawn_attacks[opposite(side)][ep] & pieces[side][PAWN];
    int captured_square = ep + (side == WHITE ? -8 : 8);
    while (candidates) {
        int from = pop_lsb(candidates);
        Bitboard occupancy = (occupied() & ~bit(from) & ~bit(captured_square)) | bit(ep);
        if (!attackers_to(kings[side], opposite(side), occupancy, bit(captured_square))) return file_of(ep);
    }
    return -1;
}
std::uint64_t Position::recompute_key() const {
    std::uint64_t result = rights_keys[rights];
    for (int square = 0; square < 64; ++square)
        if (board[square]) result ^= piece_keys[board[square]][square];
    if (side == BLACK) result ^= side_key;
    int ep_file = hashable_ep_file();
    if (ep_file >= 0) result ^= ep_keys[ep_file];
    return result;
}

void Position::generate(MoveList& moves, bool tactical_only) const {
    moves.size = 0;
    const Color them = opposite(side);
    const Bitboard occupancy = occupied();
    const Bitboard targets = (tactical_only ? colors[them] : ~colors[side]) & ~pieces[them][KING];
    Bitboard pawns = pieces[side][PAWN];
    const int step = side == WHITE ? 8 : -8;
    auto add_pawn_move = [&](int from, int to, Move flags) {
        if (relative_rank(side, to) == 7) {
            for (PieceType promotion : {QUEEN, KNIGHT, ROOK, BISHOP}) moves.add(move_of(from, to, flags, promotion));
        } else moves.add(move_of(from, to, flags));
    };
    while (pawns) {
        int from = pop_lsb(pawns), to = from + step;
        if (to >= 0 && to < 64 && board[to] == 0) {
            if (!tactical_only || relative_rank(side, to) == 7) add_pawn_move(from, to, 0);
            int double_to = to + step;
            if (!tactical_only && relative_rank(side, from) == 1 && board[double_to] == 0)
                moves.add(move_of(from, double_to, DOUBLE_PUSH));
        }
        Bitboard captures = pawn_attacks[side][from] & colors[them] & ~pieces[them][KING];
        while (captures) add_pawn_move(from, pop_lsb(captures), CAPTURE);
        if (ep >= 0 && (pawn_attacks[side][from] & bit(ep))) moves.add(move_of(from, ep, CAPTURE | EN_PASSANT));
    }
    for (PieceType type : {KNIGHT, BISHOP, ROOK, QUEEN, KING}) {
        Bitboard movers = pieces[side][type];
        while (movers) {
            int from = pop_lsb(movers);
            Bitboard attacks = 0;
            switch (type) {
            case KNIGHT: attacks = knight_attacks[from]; break;
            case BISHOP: attacks = bishop_attacks(from, occupancy); break;
            case ROOK: attacks = rook_attacks(from, occupancy); break;
            case QUEEN: attacks = queen_attacks(from, occupancy); break;
            case KING: attacks = king_attacks[from]; break;
            default: break;
            }
            attacks &= targets;
            while (attacks) {
                int to = pop_lsb(attacks);
                moves.add(move_of(from, to, board[to] ? CAPTURE : 0));
            }
        }
    }
    if (tactical_only) return;
    int base = side == WHITE ? 0 : 56;
    int flags = rights >> (side == WHITE ? 0 : 2);
    if (board[base + 4] != piece(side, KING) || attacked(base + 4, them)) return;
    if ((flags & 1) && board[base + 7] == piece(side, ROOK)
        && !board[base + 5] && !board[base + 6] && !attacked(base + 5, them) && !attacked(base + 6, them))
        moves.add(move_of(base + 4, base + 6, CASTLING));
    if ((flags & 2) && board[base] == piece(side, ROOK)
        && !board[base + 1] && !board[base + 2] && !board[base + 3]
        && !attacked(base + 3, them) && !attacked(base + 2, them))
        moves.add(move_of(base + 4, base + 2, CASTLING));
}

Undo Position::save(Move move) const {
    Undo undo;
    undo.move = move;
    undo.rights = rights; undo.ep = ep; undo.halfmove = halfmove; undo.fullmove = fullmove;
    undo.key = key; undo.pawn_key = pawn_key;
    undo.mg = mg; undo.eg = eg; undo.phase = phase;
    return undo;
}
void Position::restore(const Undo& undo) {
    rights = undo.rights; ep = undo.ep; halfmove = undo.halfmove; fullmove = undo.fullmove;
    key = undo.key; pawn_key = undo.pawn_key;
    mg = undo.mg; eg = undo.eg; phase = undo.phase;
}

bool Position::make(Move move) {
    assert(move);
    const int from = from_sq(move), to = to_sq(move);
    int moving = board[from];
    assert(moving && color_of(moving) == side);
    Undo undo = save(move);
    int captured_square = move & EN_PASSANT ? to + (side == WHITE ? -8 : 8) : to;
    undo.captured = board[captured_square];
    assert(!undo.captured || (color_of(undo.captured) != side && type_of(undo.captured) != KING));
    history.push_back(undo);
    int old_ep_file = hashable_ep_file();
    if (old_ep_file >= 0) key ^= ep_keys[old_ep_file];
    key ^= rights_keys[rights];
    ep = -1;
    remove(from);
    if (undo.captured) remove(captured_square);
    put(to, is_promotion(move) ? piece(side, promotion_of(move)) : moving);
    if (move & CASTLING) {
        int rook_from = to > from ? from + 3 : from - 4;
        int rook_to = to > from ? from + 1 : from - 1;
        remove(rook_from);
        put(rook_to, piece(side, ROOK));
    }
    rights &= castle_mask(from) & castle_mask(to);
    key ^= rights_keys[rights];
    if (move & DOUBLE_PUSH) ep = (from + to) / 2;
    halfmove = type_of(moving) == PAWN || undo.captured ? 0 : std::min(halfmove + (halfmove < 2147483647), 2147483647);
    if (side == BLACK && fullmove < 2147483647) ++fullmove;
    Color us = side;
    side = opposite(side);
    key ^= side_key;
    int new_ep_file = hashable_ep_file();
    if (new_ep_file >= 0) key ^= ep_keys[new_ep_file];
    if (attacked(kings[us], side)) { unmake(); return false; }
    return true;
}

void Position::unmake() {
    assert(!history.empty() && history.back().move);
    Undo undo = history.back();
    history.pop_back();
    side = opposite(side);
    int from = from_sq(undo.move), to = to_sq(undo.move);
    int moving = board[to];
    remove(to);
    put(from, is_promotion(undo.move) ? piece(side, PAWN) : moving);
    if (undo.move & CASTLING) {
        int rook_from = to > from ? from + 3 : from - 4;
        int rook_to = to > from ? from + 1 : from - 1;
        remove(rook_to);
        put(rook_from, piece(side, ROOK));
    }
    if (undo.captured) {
        int captured_square = undo.move & EN_PASSANT ? to + (side == WHITE ? -8 : 8) : to;
        put(captured_square, undo.captured);
    }
    restore(undo);
}
void Position::make_null() {
    assert(!in_check());
    history.push_back(save(NO_MOVE));
    int old_ep_file = hashable_ep_file();
    if (old_ep_file >= 0) key ^= ep_keys[old_ep_file];
    ep = -1;
    // A search-only null move is a repetition barrier and never advances the game clock.
    halfmove = 0;
    side = opposite(side);
    key ^= side_key;
}
void Position::unmake_null() {
    assert(!history.empty() && history.back().move == NO_MOVE);
    Undo undo = history.back();
    history.pop_back();
    side = opposite(side);
    restore(undo);
}

MoveList Position::legal_moves() {
    MoveList pseudo, legal;
    generate(pseudo);
    for (Move move : pseudo) if (make(move)) { legal.add(move); unmake(); }
    return legal;
}
Move Position::parse_move(std::string_view text) {
    for (Move move : legal_moves()) if (move_name(move) == text) return move;
    return NO_MOVE;
}
bool Position::has_legal_move() {
    MoveList moves;
    generate(moves);
    for (Move move : moves) if (make(move)) { unmake(); return true; }
    return false;
}
bool Position::repetition(int search_ply) const {
    int count = 1;
    int end = int(history.size());
    int earliest = std::max(0, end - halfmove);
    for (int index = end - 2; index >= earliest; index -= 2) {
        if (history[index].key == key) {
            ++count;
            if (count >= 3 || (search_ply > 0 && index >= end - search_ply)) return true;
        }
    }
    return false;
}
bool Position::insufficient_material() const {
    if (pieces[WHITE][PAWN] || pieces[BLACK][PAWN] || pieces[WHITE][ROOK] || pieces[BLACK][ROOK]
        || pieces[WHITE][QUEEN] || pieces[BLACK][QUEEN]) return false;
    Bitboard bishops = pieces[WHITE][BISHOP] | pieces[BLACK][BISHOP];
    Bitboard knights = pieces[WHITE][KNIGHT] | pieces[BLACK][KNIGHT];
    if (std::popcount(bishops | knights) <= 1) return true;
    constexpr Bitboard dark = 0xaa55aa55aa55aa55ULL;
    return !knights && (!(bishops & dark) || !(bishops & ~dark));
}
bool Position::drawn(int search_ply) {
    if (insufficient_material() || repetition(search_ply)) return true;
    // Checkmate takes precedence over a fifty-move draw.
    return halfmove >= 100 && (!in_check() || has_legal_move());
}

int Position::see(Move move) const {
    if (move & CASTLING) return 0;
    int from = from_sq(move), to = to_sq(move);
    int victim = move & EN_PASSANT ? piece(opposite(side), PAWN) : board[to];
    std::array<int, 32> gain{};
    gain[0] = victim ? material_values[type_of(victim)] : 0;
    PieceType on_target = is_promotion(move) ? promotion_of(move) : type_of(board[from]);
    if (is_promotion(move)) gain[0] += material_values[on_target] - material_values[PAWN];
    Bitboard occupancy = (occupied() & ~bit(from)) | bit(to);
    if (move & EN_PASSANT) occupancy &= ~bit(to + (side == WHITE ? -8 : 8));
    Color by = opposite(side);
    int depth = 0;
    while (depth < 30) {
        Bitboard attackers = attackers_to(to, by, occupancy);
        if (!attackers) break;
        PieceType attacker_type = PAWN;
        Bitboard candidates = 0;
        for (int type = PAWN; type <= KING; ++type) {
            candidates = attackers & pieces[by][type];
            if (candidates) { attacker_type = PieceType(type); break; }
        }
        int attacker = std::countr_zero(candidates);
        Bitboard next_occupancy = occupancy & ~bit(attacker);
        if (attacker_type == KING && attackers_to(to, opposite(by), next_occupancy)) break;
        ++depth;
        gain[depth] = material_values[on_target] - gain[depth - 1];
        on_target = attacker_type;
        if (attacker_type == PAWN && relative_rank(by, to) == 7) {
            gain[depth] += material_values[QUEEN] - material_values[PAWN];
            on_target = QUEEN;
        }
        occupancy = next_occupancy;
        by = opposite(by);
    }
    while (depth > 0) {
        gain[depth - 1] = -std::max(-gain[depth - 1], gain[depth]);
        --depth;
    }
    return gain[0];
}

bool Position::consistent() const {
    Position rebuilt(true);
    for (int square = 0; square < 64; ++square) if (board[square]) rebuilt.put(square, board[square]);
    return pieces == rebuilt.pieces && colors == rebuilt.colors && kings == rebuilt.kings
        && mg == rebuilt.mg && eg == rebuilt.eg && phase == rebuilt.phase
        && pawn_key == rebuilt.pawn_key && key == recompute_key();
}
std::uint64_t perft(Position& position, int depth) {
    if (depth == 0) return 1;
    MoveList moves;
    position.generate(moves);
    std::uint64_t nodes = 0;
    for (Move move : moves) {
        if (!position.make(move)) continue;
        nodes += depth == 1 ? 1 : perft(position, depth - 1);
        position.unmake();
    }
    return nodes;
}

} // namespace aurora
