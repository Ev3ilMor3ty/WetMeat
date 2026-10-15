#pragma once

#include "chess.hpp"
#include "evaluate.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <limits>
#include <memory>
#include <mutex>
#include <thread>

namespace aurora {

constexpr int MAX_PLY = 128;
constexpr int MATE_SCORE = 32000;
constexpr int MATE_BOUND = 31000;
constexpr int INFINITY_SCORE = 32700;
enum Bound : int { NO_BOUND, EXACT, LOWER, UPPER };

struct TTRecord {
    Move move = NO_MOVE;
    int score = 0;
    int evaluation = 0;
    int depth = 0;
    Bound bound = NO_BOUND;
    int generation = 0;
};

class TranspositionTable {
public:
    explicit TranspositionTable(std::size_t megabytes = 64);
    void resize(std::size_t megabytes);
    void clear();
    void new_search() { generation = (generation + 1) & 15; }
    bool probe(std::uint64_t key, TTRecord& record) const;
    void store(std::uint64_t key, Move move, int score, int evaluation, int depth, Bound bound);
    int hashfull() const;

private:
    struct Slot {
        std::atomic<std::uint64_t> data{0};
        std::atomic<std::uint64_t> key{0};
    };
    struct alignas(64) Bucket { std::array<Slot, 4> slots; };
    std::unique_ptr<Bucket[]> buckets;
    std::size_t bucket_count = 0;
    int generation = 0;
};

struct Limits {
    int depth = 0;
    std::uint64_t nodes = 0;
    std::int64_t movetime = -1;
    std::array<std::int64_t, 2> time{{-1, -1}};
    std::array<std::int64_t, 2> increment{};
    int moves_to_go = 0;
    int mate = 0;
    bool infinite = false;
    bool ponder = false;
    std::vector<Move> searchmoves;
};

struct SearchControl {
    explicit SearchControl(const Limits& limits, Color side, int overhead);
    std::atomic<bool> stop{false};
    std::atomic<bool> external_stop{false};
    std::atomic<bool> pondering{false};
    std::atomic<std::uint64_t> nodes{0};
    std::atomic<std::int64_t> start_ns{0};
    std::int64_t soft_ms = std::numeric_limits<std::int64_t>::max();
    std::int64_t hard_ms = std::numeric_limits<std::int64_t>::max();
    std::uint64_t node_limit = 0;
    std::condition_variable wake;
    std::mutex mutex;
    std::int64_t elapsed_ms() const;
    void ponder_hit();
    static std::int64_t now_ns();
};

struct SearchResult {
    Move bestmove = NO_MOVE;
    int score = 0;
    int depth = 0;
    std::uint64_t local_nodes = 0;
    std::vector<Move> pv;
};

using Reporter = std::function<void(const std::string&)>;

class Search {
public:
    Search(TranspositionTable& table, SearchControl& control, Reporter report = {}, int worker_id = 0, int neural_weight = -1);
    SearchResult run(Position position, const Limits& limits);

private:
    struct Stack { Move move = NO_MOVE; int piece = 0; int static_eval = 0; };
    TranspositionTable& tt;
    SearchControl& control;
    Reporter report;
    Evaluator evaluator;
    int worker_id;
    int seldepth = 0;
    std::uint64_t local_nodes = 0;
    std::array<std::array<std::array<int, 64>, 64>, 2> history{};
    std::array<std::array<Move, 2>, MAX_PLY> killers{};
    std::array<std::array<Move, 64>, 13> counters{};
    std::array<Stack, MAX_PLY> stack{};
    std::array<std::array<Move, MAX_PLY>, MAX_PLY> pv{};
    std::array<int, MAX_PLY> pv_length{};
    std::array<std::array<int, 256>, MAX_PLY> reductions{};
    std::vector<Move> allowed_root_moves;

    bool visit_node(int ply);
    int negamax(Position& position, int depth, int alpha, int beta, int ply, bool allow_null);
    int quiescence(Position& position, int alpha, int beta, int ply);
    int move_score(const Position& position, Move move, Move tt_move, int ply) const;
    void update_history(Color side, Move move, int bonus);
    void update_pv(int ply, Move move);
    void print_info(const SearchResult& result);
};

class Engine {
public:
    explicit Engine(Reporter report);
    ~Engine();
    void start(const Position& position, const Limits& limits);
    void stop();
    void ponder_hit();
    void clear();
    void set_hash(std::size_t megabytes);
    void set_threads(int count);
    void set_overhead(int milliseconds);
    void set_neural(bool enabled);
    void set_neural_weight(int weight);
    int evaluate(const Position& position) const;

private:
    Reporter report;
    TranspositionTable tt;
    int thread_count = 1;
    int move_overhead = 20;
    bool use_neural = neural::available();
    int neural_weight = 100;
    std::shared_ptr<SearchControl> active;
    std::thread worker;
};

int score_to_tt(int score, int ply);
int score_from_tt(int score, int ply);
std::string uci_score(int score);

} // namespace aurora
