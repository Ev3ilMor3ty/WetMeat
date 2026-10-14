#include "chess.hpp"
#include "evaluate.hpp"
#include "search.hpp"

#include <array>
#include <atomic>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

using namespace aurora;

namespace {
int checks = 0;
void require(bool condition, const std::string& message) {
    ++checks;
    if (!condition) throw std::runtime_error(message);
}
Position load(const std::string& fen) {
    Position position;
    std::string error;
    require(position.set_fen(fen, error), "FEN rejected: " + fen + " / " + error);
    require(position.consistent(), "Inconsistent loaded position");
    return position;
}
void play(Position& position, const std::string& text) {
    Move move = position.parse_move(text);
    require(move != NO_MOVE, "Illegal move: " + text);
    require(position.make(move), "make rejected legal move");
    require(position.consistent(), "Inconsistent after " + text);
}
void test_perft(bool extended) {
    struct Case { const char* name; const char* fen; std::array<std::uint64_t, 5> counts; };
    const std::array<Case, 5> cases{{
        {"start", Position::START_FEN.data(), {20, 400, 8902, 197281, 4865609}},
        {"kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", {48, 2039, 97862, 4085603, 193690690}},
        {"rook ending", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", {14, 191, 2812, 43238, 674624}},
        {"promotions and checks", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", {6, 264, 9467, 422333, 15833292}},
        {"underpromotions", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", {44, 1486, 62379, 2103487, 89941194}}
    }};
    for (const Case& test : cases) {
        Position position = load(test.fen);
        for (int depth = 1; depth <= (extended ? 4 : 3); ++depth) {
            auto actual = perft(position, depth);
            require(actual == test.counts[depth - 1], std::string(test.name) + " perft " + std::to_string(depth)
                + ": expected " + std::to_string(test.counts[depth - 1]) + ", got " + std::to_string(actual));
            require(position.fen() == test.fen && position.consistent(), "perft damaged position");
        }
        std::cout << "PASS perft: " << test.name << '\n';
    }
    if (extended) {
        Position position;
        require(perft(position, 5) == 4865609, "start perft 5");
    }
}
void test_moves_and_hashes() {
    Position position;
    const std::string initial = position.fen();
    const auto initial_key = position.key;
    for (const auto* move : {"e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1"}) play(position, move);
    require(position.board[6] == piece(WHITE, KING) && position.board[5] == piece(WHITE, ROOK), "castling placement");
    while (!position.history.empty()) { position.unmake(); require(position.consistent(), "unmake consistency"); }
    require(position.fen() == initial && position.key == initial_key, "unmake failed round trip");
    position.make_null();
    require(position.consistent() && position.side == BLACK && position.halfmove == 0, "null move consistency");
    position.unmake_null();
    require(position.fen() == initial && position.key == initial_key, "null move round trip");
    Position ep = load("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1");
    play(ep, "e5d6");
    require(ep.board[35] == 0 && ep.board[43] == piece(WHITE, PAWN), "en passant capture");
    ep.unmake();
    require(ep.fen() == "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1" && ep.consistent(), "en passant undo");
    Position pinned_ep = load("4k3/8/8/r4pPK/8/8/8/8 w - f6 0 1");
    require(!pinned_ep.parse_move("g5f6"), "illegal pinned en passant allowed");
    Position no_ep = load("4k3/8/8/r4pPK/8/8/8/8 w - - 0 1");
    require(pinned_ep.key == no_ep.key, "illegal en passant changed repetition hash");
    Position legal_no_ep = load("4k3/8/8/3pP3/8/8/8/4K3 w - - 0 1");
    require(legal_no_ep.key != ep.key, "legal en passant missing from hash");
    Position promotion = load("7k/P7/8/8/8/8/8/7K w - - 0 1");
    for (const auto* name : {"a7a8q", "a7a8r", "a7a8b", "a7a8n"}) {
        play(promotion, name);
        promotion.unmake();
        require(promotion.consistent(), "promotion undo");
    }
    std::cout << "PASS make/unmake, castling, en passant, promotion, hashing\n";
}
void test_draws_and_validation() {
    Position position;
    for (const auto* name : {"g1f3", "g8f6", "f3g1", "f6g8"}) play(position, name);
    require(!position.repetition(), "twofold treated as threefold");
    require(position.repetition(4), "search repetition undetected");
    for (const auto* name : {"g1f3", "g8f6", "f3g1", "f6g8"}) play(position, name);
    require(position.repetition() && position.drawn(), "threefold undetected");
    position.make_null();
    require(!position.repetition(9), "null move failed repetition barrier");
    position.unmake_null();
    auto bare = load("8/8/8/8/8/8/4k3/6K1 w - - 0 1");
    require(bare.insufficient_material(), "bare kings not drawn");
    auto knight = load("8/8/8/8/8/8/4k3/5NK1 w - - 0 1");
    require(knight.insufficient_material(), "single knight not drawn");
    auto fifty = load("7k/8/8/8/8/8/8/R5K1 w - - 100 51");
    require(fifty.drawn(), "fifty-move rule missed");
    auto mate = load("7k/6Q1/6K1/8/8/8/8/8 b - - 100 51");
    require(mate.in_check() && !mate.has_legal_move() && !mate.drawn(), "draw overrode checkmate");
    auto stalemate = load("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1");
    require(!stalemate.in_check() && !stalemate.has_legal_move(), "stalemate detection");
    std::string error, before = position.fen();
    for (const auto* fen : {"", "8/8/8/8/8/8/8/8 w - - 0 1", "8/8/8/8/8/8/4k3/6K1 x - - 0 1",
                           "8/8/8/8/8/8/4k3/6K1 w K - 0 1", "8/8/8/8/8/8/4k3/6K1 w - - -1 1"}) {
        require(!position.set_fen(fen, error), "invalid FEN accepted");
        require(position.fen() == before, "invalid FEN changed position");
    }
    std::cout << "PASS draws, mate precedence, input validation\n";
}
void test_random_round_trips() {
    std::uint64_t random = 1234567;
    Evaluator evaluator;
    for (int game = 0; game < 30; ++game) {
        Position position;
        for (int ply = 0; ply < 180; ++ply) {
            auto moves = position.legal_moves();
            if (!moves.size) break;
            random ^= random << 13; random ^= random >> 7; random ^= random << 17;
            require(position.make(moves.moves[random % moves.size]), "random legal move failed");
            require(position.consistent(), "random position inconsistent");
            require(std::abs(evaluator.evaluate(position)) <= 28000, "evaluation out of range");
        }
        while (!position.history.empty()) { position.unmake(); require(position.consistent(), "random unmake inconsistent"); }
        require(position.fen() == Position::START_FEN, "random game round trip failed");
    }
    std::cout << "PASS 30 random make/unmake games\n";
}
void test_search_and_table() {
    require(score_from_tt(score_to_tt(MATE_SCORE - 7, 4), 4) == MATE_SCORE - 7, "positive mate TT conversion");
    require(score_from_tt(score_to_tt(-MATE_SCORE + 7, 4), 4) == -MATE_SCORE + 7, "negative mate TT conversion");
    require(score_from_tt(score_to_tt(MATE_SCORE - 7, 4), 2) == MATE_SCORE - 5, "mate distance at another ply");
    TranspositionTable table(1);
    table.new_search();
    Move stored = move_of(8, 16);
    table.store(123456789, stored, -301, 77, 9, EXACT);
    TTRecord record;
    require(table.probe(123456789, record), "TT probe miss");
    require(record.move == stored && record.score == -301 && record.evaluation == 77 && record.depth == 9 && record.bound == EXACT,
            "TT packing round trip");
    require(!table.probe(123456788, record), "TT false hit");
    table.clear();
    require(!table.probe(123456789, record), "TT clear failed");
    std::atomic<bool> corrupted{false};
    std::vector<std::thread> workers;
    for (int id = 0; id < 4; ++id) {
        workers.emplace_back([&, id] {
            for (int index = 0; index < 20000; ++index) {
                // Force concurrent collisions in one bucket, with independently checkable payloads.
                std::uint64_t key = (std::uint64_t(index % 8 + id * 8 + 1) << 32) | 17;
                int expected = int(key >> 32);
                table.store(key, stored, expected, -expected, expected, EXACT);
                TTRecord found;
                if (table.probe(key, found)
                    && (found.score != expected || found.evaluation != -expected || found.move != stored || found.depth != expected))
                    corrupted.store(true);
            }
        });
    }
    for (auto& worker : workers) worker.join();
    require(!corrupted.load(), "concurrent TT snapshot corruption");
    Limits limits;
    limits.depth = 6;
    const std::array<const char*, 3> mates{{
        "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1",
        "2r3k1/5ppp/4p3/3pP3/3P4/2R2N2/5PPP/6K1 w - - 0 1",
        "8/8/8/8/8/1k6/2q5/K7 b - - 0 1"
    }};
    for (const auto* fen : mates) {
        Position position = load(fen);
        table.clear();
        SearchControl control(limits, position.side, 0);
        auto search = std::make_unique<Search>(table, control);
        auto result = search->run(position, limits);
        require(result.bestmove && position.make(result.bestmove), "search returned illegal mate move");
        require(position.in_check() && !position.has_legal_move(), "search failed mate in one");
        require(result.score == MATE_SCORE - 1, "wrong mate score");
    }
    Position position;
    limits.depth = 0;
    limits.nodes = 2048;
    SearchControl control(limits, position.side, 0);
    auto search = std::make_unique<Search>(table, control);
    auto result = search->run(position, limits);
    require(result.bestmove != NO_MOVE, "no legal fallback under node limit");
    require(control.nodes.load() <= 2048 && control.stop.load(), "node limit not enforced");
    std::cout << "PASS search, mate distances, exact node limit, 80,000 concurrent TT operations\n";
}
} // namespace

int main(int argc, char** argv) {
    try {
        bool extended = argc > 1 && std::string(argv[1]) == "--extended";
        test_perft(extended);
        test_moves_and_hashes();
        test_draws_and_validation();
        test_random_round_trips();
        test_search_and_table();
        std::cout << "All " << checks << " checks passed.\n";
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
