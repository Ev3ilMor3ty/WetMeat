#include "neural.hpp"

#include <algorithm>
#include <cstdlib>

#if __has_include("generated/neural_weights.hpp")
#include "generated/neural_weights.hpp"
#else
namespace aurora::neural::weights {
constexpr bool AVAILABLE = false;
constexpr char MODEL_ID[] = "none";
constexpr std::array<std::int16_t, FEATURES * HIDDEN> INPUT{};
constexpr std::array<std::int16_t, HIDDEN> BIAS{};
constexpr std::array<std::int16_t, HIDDEN> OUTPUT{};
}
#endif

namespace aurora::neural {

bool available() { return weights::AVAILABLE; }
std::string_view model_id() { return weights::MODEL_ID; }
void Network::clear() { for (auto& frame : cache) frame.valid = false; }

Network::Mapping Network::mapping(const Position& position, Color perspective) {
    int oriented = position.kings[perspective] ^ (perspective == BLACK ? 56 : 0);
    int mirror = file_of(oriented) >= 4 ? 7 : 0;
    int normalized = oriented ^ mirror;
    return {rank_of(normalized) / 2 * 2 + file_of(normalized) / 2,
            (perspective == BLACK ? 56 : 0) ^ mirror};
}
int Network::feature(int p, int square, Color perspective, Mapping map) {
    int plane = int(type_of(p)) + (color_of(p) == perspective ? 0 : 6);
    return map.bucket * 768 + plane * 64 + (square ^ map.transform);
}
void Network::change(Frame& frame, Color perspective, int p, int square, int sign) {
    int offset = feature(p, square, perspective, frame.mapping[perspective]) * HIDDEN;
    for (int hidden = 0; hidden < HIDDEN; ++hidden)
        frame.accumulator[perspective][hidden] += sign * weights::INPUT[offset + hidden];
}
void Network::refresh(Frame& frame, Color perspective, const Position& position) {
    frame.mapping[perspective] = mapping(position, perspective);
    for (int hidden = 0; hidden < HIDDEN; ++hidden) frame.accumulator[perspective][hidden] = weights::BIAS[hidden];
    for (int square = 0; square < 64; ++square)
        if (position.board[square]) change(frame, perspective, position.board[square], square, 1);
}
Network::Frame& Network::prepare(const Position& position) {
    auto count = position.history.size();
    Frame& frame = cache[count % CACHE_SLOTS];
    if (frame.valid && frame.key == position.key) return frame;
    const Frame* parent = nullptr;
    if (count) {
        const Frame& previous = cache[(count - 1) % CACHE_SLOTS];
        if (previous.valid && previous.key == position.history.back().key) parent = &previous;
    }
    for (Color perspective : {WHITE, BLACK}) {
        Mapping map = mapping(position, perspective);
        if (!parent || !(parent->mapping[perspective] == map)) {
            refresh(frame, perspective, position);
            continue;
        }
        frame.mapping[perspective] = map;
        frame.accumulator[perspective] = parent->accumulator[perspective];
        const Undo& undo = position.history.back();
        if (!undo.move) continue; // Null moves change the turn but no input features.
        int from = from_sq(undo.move), to = to_sq(undo.move);
        Color mover = opposite(position.side);
        int after = position.board[to];
        int before = is_promotion(undo.move) ? piece(mover, PAWN) : after;
        change(frame, perspective, before, from, -1);
        change(frame, perspective, after, to, 1);
        if (undo.captured) {
            int captured_square = undo.move & EN_PASSANT ? to + (mover == WHITE ? -8 : 8) : to;
            change(frame, perspective, undo.captured, captured_square, -1);
        }
        if (undo.move & CASTLING) {
            int rook_from = to > from ? from + 3 : from - 4;
            int rook_to = to > from ? from + 1 : from - 1;
            change(frame, perspective, piece(mover, ROOK), rook_from, -1);
            change(frame, perspective, piece(mover, ROOK), rook_to, 1);
        }
    }
    frame.key = position.key;
    frame.valid = true;
    return frame;
}
int Network::correction(const Position& position) {
    if (!weights::AVAILABLE) return 0;
    const Frame& frame = prepare(position);
    std::int64_t sum = 0;
    for (int hidden = 0; hidden < HIDDEN; ++hidden) {
        int white = std::clamp(frame.accumulator[WHITE][hidden], 0, FEATURE_SCALE);
        int black = std::clamp(frame.accumulator[BLACK][hidden], 0, FEATURE_SCALE);
        sum += std::int64_t(white - black) * weights::OUTPUT[hidden];
    }
    // Bounded residual keeps the classical material scale and mate scores intact.
    constexpr std::int64_t denominator = std::int64_t(FEATURE_SCALE) * OUTPUT_SCALE;
    return int(CORRECTION_LIMIT * sum / (denominator + std::abs(sum)));
}

} // namespace aurora::neural
