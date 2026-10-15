#include "search.hpp"

#include <algorithm>
#include <charconv>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>

namespace aurora {

namespace {
constexpr const char* VERSION = "Aurora 1.1.0";
std::mutex output_mutex;

void output(const std::string& line) {
    std::lock_guard<std::mutex> lock(output_mutex);
    std::cout << line << std::endl;
}
void error(const std::string& message) { output("info string Fehler: " + message); }

std::vector<std::string> split(const std::string& line) {
    std::istringstream input(line);
    std::vector<std::string> tokens;
    for (std::string token; input >> token;) tokens.push_back(std::move(token));
    return tokens;
}
std::string join(const std::vector<std::string>& tokens, std::size_t first, std::size_t last) {
    std::string result;
    for (std::size_t index = first; index < last; ++index) {
        if (index != first) result += ' ';
        result += tokens[index];
    }
    return result;
}
std::optional<std::int64_t> number(std::string_view text, std::int64_t minimum, std::int64_t maximum) {
    std::int64_t value = 0;
    auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (ec != std::errc{} || end != text.data() + text.size() || value < minimum || value > maximum) return {};
    return value;
}

void divide(Position position, int depth, bool uci) {
    auto start = std::chrono::steady_clock::now();
    std::uint64_t total = 0;
    if (depth == 0) total = 1;
    else {
        for (Move move : position.legal_moves()) {
            position.make(move);
            auto count = perft(position, depth - 1);
            position.unmake();
            output(std::string(uci ? "info string " : "") + move_name(move) + ": " + std::to_string(count));
            total += count;
        }
    }
    auto milliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
    output(std::string(uci ? "info string " : "") + "nodes " + std::to_string(total)
        + " time " + std::to_string(milliseconds) + " nps " + std::to_string(total * 1000 / std::max<std::int64_t>(1, milliseconds)));
}

bool set_position(Position& position, const std::vector<std::string>& tokens) {
    Position candidate;
    std::size_t index = 1;
    if (index >= tokens.size()) { error("position braucht startpos oder fen"); return false; }
    if (tokens[index] == "startpos") ++index;
    else if (tokens[index] == "fen") {
        if (tokens.size() < index + 7) { error("FEN muss sechs Felder enthalten"); return false; }
        std::string reason;
        if (!candidate.set_fen(join(tokens, index + 1, index + 7), reason)) { error(reason); return false; }
        index += 7;
    } else { error("Unbekanntes Positionsformat"); return false; }
    if (index < tokens.size()) {
        if (tokens[index++] != "moves") { error("Nach der Position muss moves folgen"); return false; }
        for (; index < tokens.size(); ++index) {
            Move move = candidate.parse_move(tokens[index]);
            if (!move) { error("Illegaler Zug " + tokens[index]); return false; }
            candidate.make(move);
        }
    }
    position = std::move(candidate);
    return true;
}

bool parse_go(Position& position, const std::vector<std::string>& tokens, Limits& limits) {
    const std::vector<std::string> keywords{
        "depth", "nodes", "movetime", "wtime", "btime", "winc", "binc", "movestogo", "mate", "infinite", "ponder", "searchmoves"
    };
    for (std::size_t index = 1; index < tokens.size(); ++index) {
        const std::string& token = tokens[index];
        if (token == "infinite") { limits.infinite = true; continue; }
        if (token == "ponder") { limits.ponder = true; continue; }
        if (token == "searchmoves") {
            std::size_t count = 0;
            while (index + 1 < tokens.size() && std::find(keywords.begin(), keywords.end(), tokens[index + 1]) == keywords.end()) {
                Move move = position.parse_move(tokens[++index]);
                if (!move) { error("Illegaler searchmoves-Zug " + tokens[index]); return false; }
                if (std::find(limits.searchmoves.begin(), limits.searchmoves.end(), move) == limits.searchmoves.end()) limits.searchmoves.push_back(move);
                ++count;
            }
            if (!count) { error("searchmoves braucht mindestens einen legalen Zug"); return false; }
            continue;
        }
        if (std::find(keywords.begin(), keywords.end(), token) == keywords.end()) { error("Unbekanntes go-Feld " + token); return false; }
        if (index + 1 >= tokens.size()) { error("Wert fuer " + token + " fehlt"); return false; }
        std::int64_t minimum = 0, maximum = 1000000000000LL;
        if (token == "depth") { minimum = 1; maximum = MAX_PLY - 2; }
        if (token == "mate") { minimum = 1; maximum = (MAX_PLY - 4) / 2; }
        if (token == "movestogo") { minimum = 1; maximum = 1000; }
        if (token == "nodes") { minimum = 1; maximum = 1000000000000000LL; }
        auto value = number(tokens[++index], minimum, maximum);
        if (!value) { error("Ungueltiger Wert fuer " + token); return false; }
        if (token == "depth") limits.depth = int(*value);
        else if (token == "mate") limits.mate = int(*value);
        else if (token == "nodes") limits.nodes = std::uint64_t(*value);
        else if (token == "movetime") limits.movetime = *value;
        else if (token == "movestogo") limits.moves_to_go = int(*value);
        else if (token == "wtime") limits.time[WHITE] = *value;
        else if (token == "btime") limits.time[BLACK] = *value;
        else if (token == "winc") limits.increment[WHITE] = *value;
        else if (token == "binc") limits.increment[BLACK] = *value;
    }
    return true;
}

void set_option(Engine& engine, const std::vector<std::string>& tokens) {
    if (tokens.size() < 3 || tokens[1] != "name") { error("setoption braucht name"); return; }
    auto separator = std::find(tokens.begin() + 2, tokens.end(), "value");
    std::size_t separator_index = separator - tokens.begin();
    std::string name = join(tokens, 2, separator_index);
    std::string value = separator == tokens.end() ? "" : join(tokens, separator_index + 1, tokens.size());
    if (name == "Clear Hash") { engine.clear(); return; }
    if (name == "Ponder") {
        if (value != "true" && value != "false") error("Ponder braucht true oder false");
        return; // Pondering is entered by 'go ponder', as required by UCI.
    }
    if (name == "Use Neural") {
        if (value != "true" && value != "false") error("Use Neural braucht true oder false");
        else if (value == "true" && !neural::available()) error("Kein trainiertes Modell eingebaut");
        else engine.set_neural(value == "true");
        return;
    }
    int minimum = 0, maximum = 0;
    if (name == "Hash") { minimum = 1; maximum = 4096; }
    else if (name == "Threads") { minimum = 1; maximum = 64; }
    else if (name == "Move Overhead") { minimum = 0; maximum = 5000; }
    else if (name == "Neural Weight") { minimum = 0; maximum = 200; }
    else { error("Unbekannte Option " + name); return; }
    auto integer = number(value, minimum, maximum);
    if (!integer) { error("Ungueltiger Optionswert fuer " + name); return; }
    try {
        if (name == "Hash") engine.set_hash(std::size_t(*integer));
        else if (name == "Threads") engine.set_threads(int(*integer));
        else if (name == "Neural Weight") engine.set_neural_weight(int(*integer));
        else engine.set_overhead(int(*integer));
    } catch (const std::exception& exception) { error(std::string("Option konnte nicht gesetzt werden: ") + exception.what()); }
}

int bench(int depth) {
    const std::array<const char*, 8> positions{{
        Position::START_FEN.data(),
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        "4k3/8/3p4/3P4/4K3/8/8/8 w - - 0 1",
        "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1",
        "2r3k1/5ppp/4p3/3pP3/3P4/2R2N2/5PPP/6K1 w - - 0 1"
    }};
    TranspositionTable table(32);
    auto start = std::chrono::steady_clock::now();
    std::uint64_t nodes = 0;
    for (std::size_t index = 0; index < positions.size(); ++index) {
        Position position;
        std::string reason;
        if (!position.set_fen(positions[index], reason)) { std::cerr << reason << '\n'; return 1; }
        Limits limits;
        limits.depth = depth;
        SearchControl control(limits, position.side, 0);
        table.clear();
        table.new_search();
        auto search = std::make_unique<Search>(table, control);
        auto result = search->run(position, limits);
        nodes += result.local_nodes;
        std::cout << index + 1 << " bestmove " << move_name(result.bestmove) << " depth " << result.depth
                  << " score " << uci_score(result.score) << " nodes " << result.local_nodes << '\n';
    }
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
    std::cout << "bench nodes " << nodes << " time " << elapsed << " nps " << nodes * 1000 / std::max<std::int64_t>(1, elapsed) << '\n';
    return 0;
}

int uci_loop() {
    Position position;
    Engine engine(output);
    for (std::string line; std::getline(std::cin, line);) {
        auto tokens = split(line);
        if (tokens.empty()) continue;
        const std::string& command = tokens[0];
        if (command == "uci") {
            output(std::string("id name ") + VERSION);
            output("id author Aurora contributors");
            output("option name Hash type spin default 64 min 1 max 4096");
            output("option name Threads type spin default 1 min 1 max 64");
            output("option name Move Overhead type spin default 20 min 0 max 5000");
            output("option name Ponder type check default false");
            output(std::string("option name Use Neural type check default ") + (neural::available() ? "true" : "false"));
            output("option name Neural Weight type spin default 100 min 0 max 200");
            output("option name Clear Hash type button");
            output("uciok");
        } else if (command == "isready") output("readyok");
        else if (command == "setoption") set_option(engine, tokens);
        else if (command == "ucinewgame") { engine.clear(); position = Position{}; }
        else if (command == "position") { engine.stop(); set_position(position, tokens); }
        else if (command == "go") {
            if (tokens.size() == 3 && tokens[1] == "perft") {
                auto depth = number(tokens[2], 0, 10);
                if (!depth) error("Perft-Tiefe muss zwischen 0 und 10 liegen");
                else { engine.stop(); divide(position, int(*depth), true); }
            } else {
                Limits limits;
                if (parse_go(position, tokens, limits)) engine.start(position, limits);
            }
        } else if (command == "stop") engine.stop();
        else if (command == "ponderhit") engine.ponder_hit();
        else if (command == "quit") { engine.stop(); return 0; }
        else if (command == "d") {
            output("info string fen " + position.fen());
            std::string legal = "info string legal";
            for (Move move : position.legal_moves()) legal += " " + move_name(move);
            output(legal);
        } else if (command == "eval") {
            output("info string evaluation cp " + std::to_string(engine.evaluate(position)));
        } else if (command != "debug" && command != "register") error("Unbekannter Befehl " + command);
    }
    engine.stop();
    return 0;
}
} // namespace
} // namespace aurora

int main(int argc, char** argv) {
    using namespace aurora;
    try {
        init_chess();
        if (argc == 1) return uci_loop();
        std::string command = argv[1];
        if (command == "--version") { std::cout << VERSION << '\n'; return 0; }
        if (command == "--perft" && argc >= 3 && argc <= 4) {
            auto depth = number(argv[2], 0, 10);
            if (!depth) throw std::runtime_error("Perft-Tiefe muss zwischen 0 und 10 liegen");
            Position position;
            std::string reason;
            if (argc == 4 && !position.set_fen(argv[3], reason)) throw std::runtime_error(reason);
            divide(position, int(*depth), false);
            return 0;
        }
        if (command == "--bench" && argc <= 3) {
            auto depth = argc == 3 ? number(argv[2], 1, 20) : std::optional<std::int64_t>(8);
            if (!depth) throw std::runtime_error("Bench-Tiefe muss zwischen 1 und 20 liegen");
            return bench(int(*depth));
        }
        std::cout << "Aurora: eigenstaendige UCI-Schachengine\n"
                  << "  aurora                   UCI-Modus\n"
                  << "  aurora --perft TIEFE [\"FEN\"]\n"
                  << "  aurora --bench [TIEFE]\n"
                  << "  aurora --version\n";
        return command == "--help" ? 0 : 1;
    } catch (const std::exception& exception) {
        std::cerr << "Aurora: " << exception.what() << '\n';
        return 1;
    }
}
