#include "search.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <sstream>

namespace aurora {

namespace {
constexpr std::uint64_t MOVE_MASK = (1ULL << 19) - 1;
std::uint64_t pack(const TTRecord& record) {
    return std::uint64_t(record.move)
        | (std::uint64_t(std::uint16_t(std::int16_t(record.score))) << 19)
        | (std::uint64_t(std::uint16_t(std::int16_t(record.evaluation))) << 35)
        | (std::uint64_t(std::clamp(record.depth, 0, 127)) << 51)
        | (std::uint64_t(record.bound) << 58)
        | (std::uint64_t(record.generation) << 60);
}
TTRecord unpack(std::uint64_t data) {
    TTRecord record;
    record.move = data & MOVE_MASK;
    record.score = std::bit_cast<std::int16_t>(std::uint16_t(data >> 19));
    record.evaluation = std::bit_cast<std::int16_t>(std::uint16_t(data >> 35));
    record.depth = (data >> 51) & 127;
    record.bound = Bound((data >> 58) & 3);
    record.generation = (data >> 60) & 15;
    return record;
}
} // namespace

TranspositionTable::TranspositionTable(std::size_t megabytes) { resize(megabytes); }
void TranspositionTable::resize(std::size_t megabytes) {
    std::size_t requested = std::max<std::size_t>(1, megabytes) * 1024 * 1024 / sizeof(Bucket);
    std::size_t count = std::bit_floor(requested);
    auto replacement = std::make_unique<Bucket[]>(count);
    buckets = std::move(replacement);
    bucket_count = count;
    generation = 0;
}
void TranspositionTable::clear() {
    for (std::size_t index = 0; index < bucket_count; ++index)
        for (auto& slot : buckets[index].slots) {
            slot.key.store(0, std::memory_order_relaxed);
            slot.data.store(0, std::memory_order_relaxed);
        }
    generation = 0;
}
bool TranspositionTable::probe(std::uint64_t key, TTRecord& record) const {
    const Bucket& bucket = buckets[key & (bucket_count - 1)];
    for (const auto& slot : bucket.slots) {
        std::uint64_t check = slot.key.load(std::memory_order_acquire);
        std::uint64_t data = slot.data.load(std::memory_order_acquire);
        // XOR verification rejects mismatched snapshots during concurrent replacement.
        if (data && (check ^ data) == key) { record = unpack(data); return true; }
    }
    return false;
}
void TranspositionTable::store(std::uint64_t key, Move move, int score, int evaluation, int depth, Bound bound) {
    Bucket& bucket = buckets[key & (bucket_count - 1)];
    Slot* replacement = &bucket.slots[0];
    int lowest = 100000;
    for (auto& slot : bucket.slots) {
        std::uint64_t check = slot.key.load(std::memory_order_acquire);
        std::uint64_t data = slot.data.load(std::memory_order_acquire);
        if (!data) { replacement = &slot; break; }
        TTRecord old = unpack(data);
        if ((check ^ data) == key) {
            if (!move) move = old.move;
            if (bound != EXACT && depth + 3 < old.depth && old.generation == generation) return;
            replacement = &slot;
            break;
        }
        int age = (generation - old.generation) & 15;
        int quality = old.depth + (old.bound == EXACT ? 3 : 0) - 8 * age;
        if (quality < lowest) { lowest = quality; replacement = &slot; }
    }
    TTRecord record{move, score, evaluation, depth, bound, generation};
    std::uint64_t data = pack(record);
    replacement->data.store(data, std::memory_order_relaxed);
    replacement->key.store(key ^ data, std::memory_order_release);
}
int TranspositionTable::hashfull() const {
    std::size_t sample = std::min<std::size_t>(250, bucket_count);
    int used = 0;
    for (std::size_t index = 0; index < sample; ++index)
        for (const auto& slot : buckets[index].slots) {
            auto data = slot.data.load(std::memory_order_relaxed);
            if (data && unpack(data).generation == generation) ++used;
        }
    return sample ? int(used * 1000 / (sample * 4)) : 0;
}

int score_to_tt(int score, int ply) {
    if (score > MATE_BOUND) return score + ply;
    if (score < -MATE_BOUND) return score - ply;
    return score;
}
int score_from_tt(int score, int ply) {
    if (score > MATE_BOUND) return score - ply;
    if (score < -MATE_BOUND) return score + ply;
    return score;
}
std::string uci_score(int score) {
    if (score > MATE_BOUND) return "mate " + std::to_string((MATE_SCORE - score + 1) / 2);
    if (score < -MATE_BOUND) return "mate " + std::to_string(-(MATE_SCORE + score) / 2);
    return "cp " + std::to_string(score);
}

std::int64_t SearchControl::now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
SearchControl::SearchControl(const Limits& limits, Color side, int overhead) {
    start_ns.store(now_ns(), std::memory_order_relaxed);
    pondering.store(limits.ponder, std::memory_order_relaxed);
    node_limit = limits.nodes;
    if (limits.infinite) return;
    if (limits.movetime >= 0) {
        soft_ms = hard_ms = std::max<std::int64_t>(1, limits.movetime - overhead);
    } else if (limits.time[side] >= 0) {
        std::int64_t available = std::max<std::int64_t>(1, limits.time[side] - overhead);
        int horizon = limits.moves_to_go > 0 ? limits.moves_to_go : 30;
        double base = double(available) / horizon + double(limits.increment[side]) * 0.75;
        soft_ms = std::max<std::int64_t>(1, std::min<std::int64_t>(available * 4 / 5, std::int64_t(base)));
        hard_ms = std::max<std::int64_t>(1, std::min<std::int64_t>(available, std::max<std::int64_t>(soft_ms * 4, soft_ms + 10)));
    }
}
std::int64_t SearchControl::elapsed_ms() const {
    return std::max<std::int64_t>(0, (now_ns() - start_ns.load(std::memory_order_relaxed)) / 1000000);
}
void SearchControl::ponder_hit() {
    std::lock_guard<std::mutex> lock(mutex);
    if (pondering.load(std::memory_order_relaxed)) {
        start_ns.store(now_ns(), std::memory_order_relaxed);
        pondering.store(false, std::memory_order_release);
        wake.notify_all();
    }
}

Search::Search(TranspositionTable& table, SearchControl& shared_control, Reporter reporter, int id)
    : tt(table), control(shared_control), report(std::move(reporter)), worker_id(id) {
    for (int depth = 1; depth < MAX_PLY; ++depth)
        for (int move = 1; move < 256; ++move)
            reductions[depth][move] = std::max(0, int(std::log(double(depth)) * std::log(double(move)) / 2.3));
}
bool Search::visit_node(int ply) {
    if (control.stop.load(std::memory_order_relaxed)) return false;
    seldepth = std::max(seldepth, ply);
    ++local_nodes;
    std::uint64_t nodes = control.nodes.fetch_add(1, std::memory_order_relaxed) + 1;
    if (control.node_limit && nodes >= control.node_limit) {
        control.stop.store(true, std::memory_order_relaxed);
        return false;
    }
    if ((local_nodes & 255) == 0 && !control.pondering.load(std::memory_order_relaxed)
        && control.elapsed_ms() >= control.hard_ms) {
        control.stop.store(true, std::memory_order_relaxed);
        return false;
    }
    return true;
}
int Search::move_score(const Position& position, Move move, Move tt_move, int ply) const {
    if (move == tt_move) return 2000000;
    if (is_capture(move)) {
        int victim = move & EN_PASSANT ? PAWN : type_of(position.board[to_sq(move)]);
        int score = 16 * material_values[victim] - material_values[type_of(position.board[from_sq(move)])];
        if (is_promotion(move)) score += material_values[promotion_of(move)];
        return (position.see(move) >= 0 ? 1100000 : -200000) + score;
    }
    if (is_promotion(move)) return 1000000 + material_values[promotion_of(move)];
    if (killers[ply][0] == move) return 900000;
    if (killers[ply][1] == move) return 800000;
    if (ply > 0 && stack[ply - 1].piece && counters[stack[ply - 1].piece][to_sq(stack[ply - 1].move)] == move)
        return 700000;
    int jitter = worker_id ? int(((move * 2654435761u) ^ (std::uint32_t(worker_id) * 2246822519u)) & 31) : 0;
    return history[position.side][from_sq(move)][to_sq(move)] + jitter;
}
void Search::update_history(Color side, Move move, int bonus) {
    int& value = history[side][from_sq(move)][to_sq(move)];
    bonus = std::clamp(bonus, -2048, 2048);
    value += bonus - value * std::abs(bonus) / 16384;
}
void Search::update_pv(int ply, Move move) {
    pv[ply][ply] = move;
    for (int index = ply + 1; index < pv_length[ply + 1]; ++index) pv[ply][index] = pv[ply + 1][index];
    pv_length[ply] = std::max(ply + 1, pv_length[ply + 1]);
}

int Search::quiescence(Position& position, int alpha, int beta, int ply) {
    if (!visit_node(ply)) return 0;
    pv_length[ply] = ply;
    if (position.drawn(ply)) return 0;
    bool check = position.in_check();
    if (ply >= MAX_PLY - 1) return evaluator.evaluate(position);
    const int original_alpha = alpha;
    const bool pv_node = beta - alpha > 1;
    TTRecord record;
    bool hit = tt.probe(position.key, record);
    int cached_score = hit ? score_from_tt(record.score, ply) : 0;
    if (hit && !pv_node && position.halfmove < 90
        && (record.bound == EXACT || (record.bound == LOWER && cached_score >= beta)
            || (record.bound == UPPER && cached_score <= alpha))) return cached_score;
    int evaluation = check ? -INFINITY_SCORE : hit ? record.evaluation : evaluator.evaluate(position);
    int best = evaluation;
    Move best_move = NO_MOVE;
    if (!check) {
        // Standing pat is invalid in stalemate, even when there are no captures.
        if (!position.has_legal_move()) return 0;
        if (evaluation >= beta) {
            tt.store(position.key, NO_MOVE, evaluation, evaluation, 0, LOWER);
            return evaluation;
        }
        alpha = std::max(alpha, evaluation);
    }
    MoveList moves;
    position.generate(moves, !check);
    std::array<int, 256> scores{};
    for (int index = 0; index < moves.size; ++index) scores[index] = move_score(position, moves.moves[index], hit ? record.move : NO_MOVE, ply);
    int legal = 0;
    for (int index = 0; index < moves.size; ++index) {
        int next = index;
        for (int candidate = index + 1; candidate < moves.size; ++candidate)
            if (scores[candidate] > scores[next]) next = candidate;
        std::swap(scores[index], scores[next]);
        std::swap(moves.moves[index], moves.moves[next]);
        Move move = moves.moves[index];
        int exchange = !check && !is_promotion(move) ? position.see(move) : 0;
        int captured_value = (move & EN_PASSANT) ? 100
            : position.board[to_sq(move)] ? material_values[type_of(position.board[to_sq(move)])] : 0;
        stack[ply].move = move;
        stack[ply].piece = position.board[from_sq(move)];
        if (!position.make(move)) continue;
        ++legal;
        bool gives_check = position.in_check();
        if (!check && !gives_check && !is_promotion(move)
            && (exchange < 0 || (evaluation + captured_value + 180 < alpha && std::abs(alpha) < MATE_BOUND))) {
            position.unmake();
            continue;
        }
        int score = -quiescence(position, -beta, -alpha, ply + 1);
        position.unmake();
        if (control.stop.load(std::memory_order_relaxed)) return 0;
        if (score > best) { best = score; best_move = move; }
        if (score > alpha) {
            alpha = score;
            update_pv(ply, move);
            if (alpha >= beta) {
                tt.store(position.key, move, score_to_tt(score, ply), check ? 0 : evaluation, 0, LOWER);
                return score;
            }
        }
    }
    if (check && !legal) best = -MATE_SCORE + ply;
    Bound bound = best >= beta ? LOWER : best > original_alpha ? EXACT : UPPER;
    tt.store(position.key, best_move, score_to_tt(best, ply), check ? 0 : evaluation, 0, bound);
    return best;
}

int Search::negamax(Position& position, int depth, int alpha, int beta, int ply, bool allow_null) {
    if (depth <= 0) return quiescence(position, alpha, beta, ply);
    if (!visit_node(ply)) return 0;
    pv_length[ply] = ply;
    if (ply > 0 && position.drawn(ply)) return 0;
    bool check = position.in_check();
    if (ply >= MAX_PLY - 1) return evaluator.evaluate(position);
    if (ply > 0) {
        alpha = std::max(alpha, -MATE_SCORE + ply);
        beta = std::min(beta, MATE_SCORE - ply - 1);
        if (alpha >= beta) return alpha;
    }
    if (check) ++depth;
    depth = std::min(depth, MAX_PLY - 1);
    const int original_alpha = alpha;
    const bool pv_node = beta - alpha > 1;
    TTRecord record;
    bool hit = tt.probe(position.key, record);
    Move tt_move = hit ? record.move : NO_MOVE;
    int tt_score = hit ? score_from_tt(record.score, ply) : 0;
    if (hit && record.depth >= depth && !pv_node && position.halfmove < 90
        && (record.bound == EXACT || (record.bound == LOWER && tt_score >= beta) || (record.bound == UPPER && tt_score <= alpha)))
        return tt_score;
    int evaluation = check ? 0 : hit ? record.evaluation : evaluator.evaluate(position);
    stack[ply].static_eval = evaluation;
    bool improving = ply >= 2 && !check && evaluation > stack[ply - 2].static_eval;
    if (!pv_node && !check && ply > 0 && std::abs(beta) < MATE_BOUND) {
        if (depth <= 5 && evaluation - (improving ? 75 : 95) * depth >= beta)
            return position.has_legal_move() ? evaluation : 0;
        if (depth <= 2 && evaluation + 220 * depth < alpha) {
            int score = quiescence(position, alpha, beta, ply);
            if (score <= alpha) return score;
        }
        if (allow_null && depth >= 3 && evaluation >= beta && position.non_pawn_material(position.side)
            && position.halfmove < 90) {
            if (!position.has_legal_move()) return 0;
            int reduction = 3 + depth / 5 + std::min(3, std::max(0, evaluation - beta) / 180);
            stack[ply].move = NO_MOVE;
            stack[ply].piece = 0;
            position.make_null();
            int score = -negamax(position, depth - reduction - 1, -beta, -beta + 1, ply + 1, false);
            position.unmake_null();
            if (control.stop.load(std::memory_order_relaxed)) return 0;
            if (score >= beta && score < MATE_BOUND) {
                if (depth < 8) return score;
                int verified = negamax(position, depth - reduction, beta - 1, beta, ply, false);
                if (control.stop.load(std::memory_order_relaxed)) return 0;
                if (verified >= beta) return verified;
            }
        }
    }
    MoveList moves;
    position.generate(moves);
    std::array<int, 256> scores{};
    for (int index = 0; index < moves.size; ++index) scores[index] = move_score(position, moves.moves[index], tt_move, ply);
    Move best_move = NO_MOVE;
    int best = -INFINITY_SCORE;
    int legal = 0, searched = 0;
    Color us = position.side;
    std::array<Move, 256> quiets{};
    int quiet_count = 0;
    for (int index = 0; index < moves.size; ++index) {
        int next = index;
        for (int candidate = index + 1; candidate < moves.size; ++candidate)
            if (scores[candidate] > scores[next]) next = candidate;
        std::swap(scores[index], scores[next]);
        std::swap(moves.moves[index], moves.moves[next]);
        Move move = moves.moves[index];
        if (ply == 0 && !allowed_root_moves.empty()
            && std::find(allowed_root_moves.begin(), allowed_root_moves.end(), move) == allowed_root_moves.end()) continue;
        bool quiet = is_quiet(move);
        int history_score = history[us][from_sq(move)][to_sq(move)];
        int exchange = !quiet && !is_promotion(move) && !check && depth <= 5 ? position.see(move) : 0;
        stack[ply].move = move;
        stack[ply].piece = position.board[from_sq(move)];
        if (!position.make(move)) continue;
        ++legal;
        bool gives_check = position.in_check();
        if (searched > 0 && !pv_node && !check && !gives_check && best > -MATE_BOUND) {
            bool skip = quiet && depth <= 3 && legal > (improving ? 8 : 5) + depth * depth * 3;
            skip = skip || (quiet && depth <= 3 && evaluation + 120 * depth + 60 <= alpha && history_score < 8000);
            skip = skip || (!quiet && !is_promotion(move) && depth <= 5 && exchange < -90 * depth);
            if (skip) { position.unmake(); continue; }
        }
        ++searched;
        if (quiet) quiets[quiet_count++] = move;
        int child_depth = depth - 1;
        int score;
        if (searched == 1) {
            score = -negamax(position, child_depth, -beta, -alpha, ply + 1, true);
        } else {
            int reduction = 0;
            if (depth >= 3 && searched >= 3 && quiet && !check && !gives_check && move != tt_move) {
                reduction = reductions[depth][std::min(searched, 255)];
                if (pv_node) --reduction;
                if (improving) --reduction;
                if (history_score > 4000) --reduction;
                if (history_score < -4000) ++reduction;
                reduction = std::clamp(reduction, 0, std::max(0, child_depth - 1));
            }
            score = -negamax(position, child_depth - reduction, -alpha - 1, -alpha, ply + 1, true);
            if (reduction && score > alpha)
                score = -negamax(position, child_depth, -alpha - 1, -alpha, ply + 1, true);
            if (pv_node && score > alpha && score < beta)
                score = -negamax(position, child_depth, -beta, -alpha, ply + 1, true);
        }
        position.unmake();
        if (control.stop.load(std::memory_order_relaxed)) return 0;
        if (score > best) { best = score; best_move = move; }
        if (score > alpha) {
            alpha = score;
            update_pv(ply, move);
            if (alpha >= beta) {
                if (quiet) {
                    int bonus = std::min(2048, 24 * depth * depth + 32 * depth);
                    update_history(us, move, bonus);
                    for (int previous = 0; previous < quiet_count - 1; ++previous) update_history(us, quiets[previous], -bonus);
                    if (killers[ply][0] != move) { killers[ply][1] = killers[ply][0]; killers[ply][0] = move; }
                    if (ply > 0 && stack[ply - 1].piece)
                        counters[stack[ply - 1].piece][to_sq(stack[ply - 1].move)] = move;
                }
                break;
            }
        }
    }
    if (!legal) return check ? -MATE_SCORE + ply : 0;
    Bound bound = best >= beta ? LOWER : best > original_alpha ? EXACT : UPPER;
    // A searchmoves result is not a bound for the unrestricted root position.
    if (ply != 0 || allowed_root_moves.empty())
        tt.store(position.key, best_move, score_to_tt(best, ply), evaluation, depth, bound);
    return best;
}

void Search::print_info(const SearchResult& result) {
    if (!report) return;
    auto elapsed = control.elapsed_ms();
    auto nodes = control.nodes.load(std::memory_order_relaxed);
    std::ostringstream output;
    output << "info depth " << result.depth << " seldepth " << seldepth << " multipv 1 score " << uci_score(result.score)
           << " nodes " << nodes << " nps " << nodes * 1000 / std::max<std::int64_t>(1, elapsed)
           << " hashfull " << tt.hashfull() << " time " << elapsed << " pv";
    for (Move move : result.pv) output << ' ' << move_name(move);
    report(output.str());
}

SearchResult Search::run(Position position, const Limits& limits) {
    allowed_root_moves = limits.searchmoves;
    SearchResult result;
    auto legal = position.legal_moves();
    for (Move move : legal) {
        if (allowed_root_moves.empty() || std::find(allowed_root_moves.begin(), allowed_root_moves.end(), move) != allowed_root_moves.end()) {
            result.bestmove = move;
            result.pv.push_back(move);
            break;
        }
    }
    if (!result.bestmove) {
        result.score = position.in_check() ? -MATE_SCORE : 0;
        print_info(result);
        return result;
    }
    result.score = evaluator.evaluate(position);
    if (position.drawn()) { result.score = 0; print_info(result); return result; }
    int maximum_depth = limits.depth > 0 ? std::min(limits.depth, MAX_PLY - 2) : MAX_PLY - 2;
    if (limits.mate > 0) maximum_depth = std::min(maximum_depth, limits.mate * 2 + 2);
    int last_score = 0;
    int stability = 0;
    for (int depth = 1; depth <= maximum_depth; ++depth) {
        if (control.stop.load(std::memory_order_relaxed)) break;
        if (worker_id && depth > 4 && (depth + worker_id) % 4 == 0) continue;
        seldepth = 0;
        int window = depth >= 5 ? 24 : INFINITY_SCORE;
        int alpha = std::max(-INFINITY_SCORE, last_score - window);
        int beta = std::min(INFINITY_SCORE, last_score + window);
        int score = 0;
        for (;;) {
            score = negamax(position, depth, alpha, beta, 0, true);
            if (control.stop.load(std::memory_order_relaxed)) break;
            if (score > alpha && score < beta) break;
            window = std::min(INFINITY_SCORE, window * 2);
            if (score <= alpha) alpha = std::max(-INFINITY_SCORE, score - window);
            if (score >= beta) beta = std::min(INFINITY_SCORE, score + window);
        }
        if (control.stop.load(std::memory_order_relaxed)) break;
        Move old_best = result.bestmove;
        if (pv_length[0] > 0) {
            result.bestmove = pv[0][0];
            result.pv.assign(pv[0].begin(), pv[0].begin() + pv_length[0]);
        }
        result.score = score;
        result.depth = depth;
        result.local_nodes = local_nodes;
        last_score = score;
        stability = old_best == result.bestmove ? stability + 1 : 0;
        print_info(result);
        if (!control.pondering.load(std::memory_order_relaxed) && !limits.infinite) {
            if (limits.mate && score > MATE_BOUND && (MATE_SCORE - score + 1) / 2 <= limits.mate) break;
            if (std::abs(score) > MATE_BOUND && depth >= MATE_SCORE - std::abs(score) + 2) break;
            double factor = stability >= 4 ? 0.85 : stability == 0 ? 1.35 : 1.0;
            if (double(control.elapsed_ms()) >= double(control.soft_ms) * factor) break;
        }
    }
    result.local_nodes = local_nodes;
    return result;
}

Engine::Engine(Reporter reporter) : report(std::move(reporter)) {}
Engine::~Engine() { stop(); }
void Engine::stop() {
    if (active) {
        {
            std::lock_guard<std::mutex> lock(active->mutex);
            active->external_stop.store(true, std::memory_order_relaxed);
            active->stop.store(true, std::memory_order_relaxed);
        }
        active->wake.notify_all();
    }
    if (worker.joinable()) worker.join();
    active.reset();
}
void Engine::ponder_hit() { if (active) active->ponder_hit(); }
void Engine::clear() { stop(); tt.clear(); }
void Engine::set_hash(std::size_t megabytes) { stop(); tt.resize(megabytes); }
void Engine::set_threads(int count) { stop(); thread_count = std::clamp(count, 1, 64); }
void Engine::set_overhead(int milliseconds) { stop(); move_overhead = std::clamp(milliseconds, 0, 5000); }
void Engine::start(const Position& position, const Limits& limits) {
    stop();
    tt.new_search();
    active = std::make_shared<SearchControl>(limits, position.side, move_overhead);
    auto control = active;
    worker = std::thread([this, position, limits, control] {
        std::vector<std::thread> helpers;
        helpers.reserve(thread_count - 1);
        try {
            for (int id = 1; id < thread_count; ++id) {
                helpers.emplace_back([this, position, limits, control, id] {
                    try {
                        auto search = std::make_unique<Search>(tt, *control, Reporter{}, id);
                        search->run(position, limits);
                    } catch (const std::exception& error) {
                        report(std::string("info string Hilfsthread: ") + error.what());
                        control->stop.store(true, std::memory_order_relaxed);
                    }
                });
            }
            auto search = std::make_unique<Search>(tt, *control, report);
            SearchResult result = search->run(position, limits);
            {
                std::unique_lock<std::mutex> lock(control->mutex);
                control->wake.wait(lock, [&] {
                    return control->external_stop.load(std::memory_order_relaxed)
                        || (!limits.infinite && !control->pondering.load(std::memory_order_acquire));
                });
            }
            control->stop.store(true, std::memory_order_relaxed);
            for (auto& helper : helpers) if (helper.joinable()) helper.join();
            report("bestmove " + move_name(result.bestmove));
        } catch (const std::exception& error) {
            control->stop.store(true, std::memory_order_relaxed);
            for (auto& helper : helpers) if (helper.joinable()) helper.join();
            report(std::string("info string Suchfehler: ") + error.what());
            report("bestmove 0000");
        }
    });
}

} // namespace aurora
