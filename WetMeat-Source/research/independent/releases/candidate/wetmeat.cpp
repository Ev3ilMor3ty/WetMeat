// WetMeat Independent: original implementation, no borrowed engine code/weights.
// SPDX-License-Identifier: GPL-3.0-or-later
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace wetmeat {
constexpr int Pawn=1, Knight=2, Bishop=3, Rook=4, Queen=5, King=6;
constexpr int Mate=30000, Infinity=32000, MaxPly=120;
constexpr int EP=1, Castle=2, Double=4;
const std::string Start="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
constexpr std::array<int,8> KnightSteps={33,31,18,14,-14,-18,-31,-33};
constexpr std::array<int,8> KingSteps={1,-1,16,-16,15,-15,17,-17};
constexpr std::array<int,7> Values={0,100,325,340,515,980,20000};
inline bool valid(int s) { return s>=0 && s<128 && !(s&0x88); }
inline int index(int side) { return side==1 ? 0 : 1; }
std::string square(int s) { return std::string{char('a'+(s&7)),char('1'+(s>>4))}; }
int parse_square(const std::string& s) {
    if(s.size()!=2 || s[0]<'a' || s[0]>'h' || s[1]<'1' || s[1]>'8') return -1;
    return (s[1]-'1')*16+s[0]-'a';
}

struct Move {
    int from=-1, to=-1, promote=0, flags=0;
    bool operator==(const Move& m) const { return from==m.from && to==m.to && promote==m.promote; }
    uint32_t pack() const {
        return from<0 ? 0 : uint32_t(from | (to<<7) | (promote<<14) | (flags<<17));
    }
    std::string uci() const {
        if(from<0) return "0000";
        std::string s=square(from)+square(to);
        if(promote) s+=std::string("  nbrqk")[promote];
        return s;
    }
};
struct Undo {
    int piece, captured, captureSquare, rights, ep, half, full;
    std::array<int,2> kings;
};

struct Zobrist {
    uint64_t pieces[2][7][128]{}, rights[16]{}, ep[8]{}, turn=0;
    Zobrist() {
        uint64_t state=0x94a32eefd627381bULL;
        auto random=[&]() {
            // Generic SplitMix64 mixer; constants are not chess evaluation data.
            uint64_t x=(state+=0x9e3779b97f4a7c15ULL);
            x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;
            x=(x^(x>>27))*0x94d049bb133111ebULL;
            return x^(x>>31);
        };
        for(auto& color:pieces) for(auto& type:color) for(auto& sq:type) sq=random();
        for(auto& x:rights) x=random();
        for(auto& x:ep) x=random();
        turn=random();
    }
};
const Zobrist Keys;

struct Board {
    std::array<int,128> cells{};
    std::array<int,2> kings{-1,-1};
    int side=1, rights=0, ep=-1, half=0, full=1;

    bool load(const std::string& fen) {
        Board fresh;
        std::istringstream in(fen);
        std::string placement, color, castling, target;
        if(!(in>>placement>>color>>castling>>target>>fresh.half>>fresh.full)) return false;
        int rank=7,file=0;
        const std::string types=" pnbrqk";
        for(char c:placement) {
            if(c=='/') { if(file!=8 || rank==0) return false; --rank; file=0; }
            else if(c>='1' && c<='8') file+=c-'0';
            else {
                char lower=char(std::tolower(static_cast<unsigned char>(c)));
                auto type=types.find(lower);
                if(type==std::string::npos || type==0 || file>=8) return false;
                int sign=c==lower ? -1 : 1;
                int sq=rank*16+file++;
                fresh.cells[sq]=sign*int(type);
                if(type==King) {
                    if(fresh.kings[index(sign)]!=-1) return false;
                    fresh.kings[index(sign)]=sq;
                }
            }
            if(file>8) return false;
        }
        if(rank!=0 || file!=8 || fresh.kings[0]<0 || fresh.kings[1]<0 ||
           (color!="w" && color!="b") || fresh.half<0 || fresh.full<1) return false;
        fresh.side=color=="w" ? 1 : -1;
        for(char c:castling) {
            if(c=='K') fresh.rights|=1; else if(c=='Q') fresh.rights|=2;
            else if(c=='k') fresh.rights|=4; else if(c=='q') fresh.rights|=8;
            else if(c!='-') return false;
        }
        fresh.ep=target=="-" ? -1 : parse_square(target);
        if(target!="-" && (fresh.ep<0 || (fresh.ep>>4)!=(fresh.side==1 ? 5 : 2))) return false;
        *this=fresh;
        return true;
    }

    bool attacked(int sq,int by) const {
        for(int d:{-1,1}) {
            int s=sq-by*16+d;
            if(valid(s) && cells[s]==by*Pawn) return true;
        }
        for(int d:KnightSteps) if(valid(sq+d) && cells[sq+d]==by*Knight) return true;
        for(int d:KingSteps) if(valid(sq+d) && cells[sq+d]==by*King) return true;
        for(int d:KingSteps) {
            bool diagonal=std::abs(d)==15 || std::abs(d)==17;
            for(int s=sq+d;valid(s);s+=d) {
                int p=cells[s];
                if(!p) continue;
                if(p==by*Queen || p==by*(diagonal ? Bishop : Rook)) return true;
                break;
            }
        }
        return false;
    }
    bool check() const { return attacked(kings[index(side)],-side); }

    bool ep_legal() {
        if(ep<0 || cells[ep]!=0 || !valid(ep-side*16) || cells[ep-side*16]!=-side*Pawn) return false;
        for(int d:{-1,1}) {
            int from=ep-side*16+d, captured=ep-side*16;
            if(!valid(from) || cells[from]!=side*Pawn) continue;
            cells[from]=cells[captured]=0; cells[ep]=side*Pawn;
            bool safe=!check();
            cells[from]=side*Pawn; cells[captured]=-side*Pawn; cells[ep]=0;
            if(safe) return true;
        }
        return false;
    }
    uint64_t key() {
        uint64_t key=Keys.rights[rights]^(side==-1 ? Keys.turn : 0);
        for(int s=0;s<128;++s) {
            if(s&0x88) { s+=7; continue; }
            int p=cells[s];
            if(p) key^=Keys.pieces[index(p>0 ? 1 : -1)][std::abs(p)][s];
        }
        if(ep_legal()) key^=Keys.ep[ep&7];
        return key;
    }
    Undo make(const Move& m) {
        int capSq=(m.flags&EP) ? m.to-side*16 : m.to;
        Undo u{cells[m.from],cells[capSq],capSq,rights,ep,half,full,kings};
        cells[m.from]=0; cells[capSq]=0;
        cells[m.to]=m.promote ? side*m.promote : u.piece;
        if(std::abs(u.piece)==King) {
            kings[index(side)]=m.to;
            rights&=side==1 ? ~3 : ~12;
        }
        if(m.flags&Castle) {
            int rookFrom=m.to>m.from ? m.from+3 : m.from-4;
            int rookTo=m.to>m.from ? m.from+1 : m.from-1;
            cells[rookTo]=cells[rookFrom]; cells[rookFrom]=0;
        }
        for(int sq:{m.from,m.to}) {
            if(sq==0) rights&=~2; else if(sq==7) rights&=~1;
            else if(sq==112) rights&=~8; else if(sq==119) rights&=~4;
        }
        ep=(m.flags&Double) ? (m.from+m.to)/2 : -1;
        half=(std::abs(u.piece)==Pawn || u.captured) ? 0 : half+1;
        if(side==-1) ++full;
        side=-side;
        return u;
    }
    void unmake(const Move& m,const Undo& u) {
        side=-side;
        cells[m.from]=u.piece; cells[m.to]=0; cells[u.captureSquare]=u.captured;
        if(m.flags&Castle) {
            int rookFrom=m.to>m.from ? m.from+3 : m.from-4;
            int rookTo=m.to>m.from ? m.from+1 : m.from-1;
            cells[rookFrom]=cells[rookTo]; cells[rookTo]=0;
        }
        rights=u.rights; ep=u.ep; half=u.half; full=u.full; kings=u.kings;
    }

    std::vector<Move> pseudo() const {
        std::vector<Move> moves;
        moves.reserve(64);
        auto addPawn=[&](int from,int to,int flags) {
            if((to>>4)==0 || (to>>4)==7)
                for(int type:{Queen,Rook,Bishop,Knight}) moves.push_back({from,to,type,flags});
            else moves.push_back({from,to,0,flags});
        };
        for(int s=0;s<128;++s) {
            if(s&0x88) { s+=7; continue; }
            int p=cells[s]*side;
            if(p<=0) continue;
            if(p==Pawn) {
                int to=s+side*16;
                if(valid(to) && !cells[to]) {
                    addPawn(s,to,0);
                    if((s>>4)==(side==1 ? 1 : 6) && !cells[to+side*16])
                        moves.push_back({s,to+side*16,0,Double});
                }
                for(int d:{-1,1}) {
                    to=s+side*16+d;
                    if(!valid(to)) continue;
                    if(cells[to]*side<0 && std::abs(cells[to])!=King) addPawn(s,to,0);
                    else if(to==ep && !cells[to] && cells[to-side*16]==-side*Pawn)
                        moves.push_back({s,to,0,EP});
                }
            } else if(p==Knight || p==King) {
                const auto& steps=p==Knight ? KnightSteps : KingSteps;
                for(int d:steps) {
                    int to=s+d;
                    if(valid(to) && cells[to]*side<=0 && std::abs(cells[to])!=King)
                        moves.push_back({s,to,0,0});
                }
            } else {
                for(int d:KingSteps) {
                    bool diagonal=std::abs(d)==15 || std::abs(d)==17;
                    if((p==Bishop && !diagonal) || (p==Rook && diagonal)) continue;
                    for(int to=s+d;valid(to);to+=d) {
                        if(cells[to]*side>0 || std::abs(cells[to])==King) break;
                        moves.push_back({s,to,0,0});
                        if(cells[to]) break;
                    }
                }
            }
        }
        int home=side==1 ? 4 : 116, shift=side==1 ? 0 : 2;
        if(cells[home]==side*King && !attacked(home,-side)) {
            if((rights&(1<<shift)) && cells[home+3]==side*Rook && !cells[home+1] && !cells[home+2] &&
               !attacked(home+1,-side) && !attacked(home+2,-side)) moves.push_back({home,home+2,0,Castle});
            if((rights&(2<<shift)) && cells[home-4]==side*Rook && !cells[home-1] && !cells[home-2] && !cells[home-3] &&
               !attacked(home-1,-side) && !attacked(home-2,-side)) moves.push_back({home,home-2,0,Castle});
        }
        return moves;
    }
    std::vector<Move> legal(bool tacticalOnly=false) {
        auto candidates=pseudo();
        std::vector<Move> result; result.reserve(candidates.size());
        int us=side;
        for(const auto& m:candidates) {
            if(tacticalOnly && !cells[m.to] && !(m.flags&EP) && !m.promote) continue;
            auto u=make(m);
            bool safe=!attacked(kings[index(us)],-us);
            unmake(m,u);
            if(safe) result.push_back(m);
        }
        return result;
    }
    bool has_legal() {
        int us=side;
        for(const auto& m:pseudo()) {
            auto u=make(m);
            bool safe=!attacked(kings[index(us)],-us);
            unmake(m,u);
            if(safe) return true;
        }
        return false;
    }
    std::string fen() const {
        std::ostringstream out;
        const std::string white=" PNBRQK",black=" pnbrqk";
        for(int r=7;r>=0;--r) {
            int empty=0;
            for(int f=0;f<8;++f) {
                int p=cells[r*16+f];
                if(!p) ++empty;
                else { if(empty) out<<empty; empty=0; out<<(p>0 ? white[p] : black[-p]); }
            }
            if(empty) out<<empty;
            if(r) out<<'/';
        }
        out<<(side==1 ? " w " : " b ");
        if(!rights) out<<'-';
        else { if(rights&1) out<<'K'; if(rights&2) out<<'Q'; if(rights&4) out<<'k'; if(rights&8) out<<'q'; }
        out<<' '<<(ep<0 ? "-" : square(ep))<<' '<<half<<' '<<full;
        return out.str();
    }
};

uint64_t perft(Board& board,int depth) {
    if(depth==0) return 1;
    auto moves=board.legal();
    if(depth==1) return moves.size();
    uint64_t sum=0;
    for(const auto& move:moves) {
        auto u=board.make(move);
        sum+=perft(board,depth-1);
        board.unmake(move,u);
    }
    return sum;
}
bool insufficient(const Board& b) {
    int knights=0,bishops=0,color=-1;
    bool same=true;
    for(int s=0;s<128;++s) {
        if(s&0x88) { s+=7; continue; }
        int p=std::abs(b.cells[s]);
        if(p==Pawn || p==Rook || p==Queen) return false;
        if(p==Knight) ++knights;
        if(p==Bishop) {
            ++bishops;
            int shade=((s&7)+(s>>4))&1;
            if(color!=-1 && color!=shade) same=false;
            color=shade;
        }
    }
    return knights+bishops<=1 || (knights==0 && same);
}

int evaluate(const Board& b) {
    // Original formula-based features; no imported piece-square tables or weights.
    int mid=0,end=0,phase=0;
    int pawns[2][8]{}, bishops[2]{}, attackUnits[2]{}, queens[2]{};
    for(int s=0;s<128;++s) {
        if(s&0x88) { s+=7; continue; }
        int p=b.cells[s];
        if(std::abs(p)==Pawn) ++pawns[index(p>0 ? 1 : -1)][s&7];
        if(std::abs(p)==Bishop) ++bishops[index(p>0 ? 1 : -1)];
        if(std::abs(p)==Queen) ++queens[index(p>0 ? 1 : -1)];
    }
    for(int s=0;s<128;++s) {
        if(s&0x88) { s+=7; continue; }
        int piece=b.cells[s];
        if(!piece) continue;
        int sign=piece>0 ? 1 : -1,type=std::abs(piece),f=s&7;
        int rank=sign==1 ? s>>4 : 7-(s>>4),us=index(sign),them=1-us;
        int center=14-std::abs(2*f-7)-std::abs(2*(s>>4)-7);
        int m=type==King ? 0 : Values[type],e=m;
        if(type==Pawn) {
            m+=rank*6+center*2; e+=rank*11+center;
            if(pawns[us][f]>1) { m-=12; e-=18; }
            bool isolated=(f==0 || pawns[us][f-1]==0) && (f==7 || pawns[us][f+1]==0);
            if(isolated) { m-=13; e-=17; }
            bool passed=true;
            for(int r=(s>>4)+sign;r>=0 && r<8;r+=sign)
                for(int file=std::max(0,f-1);file<=std::min(7,f+1);++file)
                    if(b.cells[r*16+file]==-sign*Pawn) passed=false;
            if(passed) {
                m+=rank*rank*3; e+=rank*rank*7;
                int next=s+sign*16;
                if(valid(next)) {
                    int ownDistance=std::max(std::abs((b.kings[us]&7)-f),std::abs((b.kings[us]>>4)-(next>>4)));
                    int enemyDistance=std::max(std::abs((b.kings[them]&7)-f),std::abs((b.kings[them]>>4)-(next>>4)));
                    e+=4*(enemyDistance-ownDistance);
                }
            }
            for(int d:{-1,1}) {
                int support=s-sign*16+d;
                if(valid(support) && b.cells[support]==sign*Pawn) { m+=8; e+=10; }
            }
        } else if(type==King) {
            m-=center*5+rank*7;
            if(rank==0 && (f==2 || f==6)) m+=24;
            e+=center*8;
            for(int d:{-1,0,1}) {
                int shield=s+sign*16+d;
                if(valid(shield) && b.cells[shield]==sign*Pawn) m+=14;
                else {
                    int distant=shield+sign*16;
                    m-=valid(distant) && b.cells[distant]==sign*Pawn ? 5 : 22;
                }
                int file=f+d;
                if(file>=0 && file<8 && pawns[us][file]==0) m-=20;
            }
        } else {
            if(type==Knight) { ++phase; m+=center*8-(rank==0 ? 15 : 0); e+=center*6; }
            if(type==Bishop) { ++phase; m+=center*4+rank*2; e+=center*4; }
            if(type==Rook) {
                phase+=2; m+=rank*2; e+=center*2;
                if(!pawns[us][f]) m+=pawns[them][f] ? 12 : 23;
                if(rank==6) { m+=22; e+=30; }
            }
            if(type==Queen) { phase+=4; m+=center*2-std::max(0,rank-2)*4; e+=center*4; }
            int mobility=0,contacts=0,enemyKing=b.kings[them];
            auto zone=[&](int target) {
                return std::abs((target&7)-(enemyKing&7))<=1 && std::abs((target>>4)-(enemyKing>>4))<=1;
            };
            if(type==Knight) {
                for(int d:KnightSteps) if(valid(s+d)) {
                    if(b.cells[s+d]*sign<=0) ++mobility;
                    if(zone(s+d)) ++contacts;
                }
            } else {
                for(int d:KingSteps) {
                    bool diagonal=std::abs(d)==15 || std::abs(d)==17;
                    if((type==Bishop && !diagonal) || (type==Rook && diagonal)) continue;
                    for(int t=s+d;valid(t);t+=d) {
                        if(zone(t)) ++contacts;
                        if(b.cells[t]*sign>0) break;
                        ++mobility;
                        if(b.cells[t]) break;
                    }
                }
            }
            int weight=type==Queen ? 1 : type==Rook ? 2 : 4;
            m+=mobility*weight; e+=mobility*weight;
            if(contacts) attackUnits[us]+=(type==Queen ? 8 : type==Rook ? 4 : 3)+std::min(contacts,4);
        }
        mid+=sign*m; end+=sign*e;
    }
    if(bishops[0]>=2) { mid+=30; end+=40; }
    if(bishops[1]>=2) { mid-=30; end-=40; }
    int whiteDanger=std::min(350,attackUnits[1]*attackUnits[1]/(queens[1] ? 2 : 4));
    int blackDanger=std::min(350,attackUnits[0]*attackUnits[0]/(queens[0] ? 2 : 4));
    mid+=blackDanger-whiteDanger;
    phase=std::min(24,phase);
    int score=(mid*phase+end*(24-phase))/24;
    return std::clamp(score*b.side+10,-Mate+1000,Mate-1000);
}

struct Entry {
    uint64_t key=0;
    uint32_t move=0;
    int16_t score=0;
    int8_t depth=-1;
    uint8_t bound=0,half=0;
};
struct Table {
    std::vector<Entry> data;
    void resize(int mb) {
        size_t count=1,max=size_t(mb)*1024*1024/sizeof(Entry);
        while(count<=max/2) count*=2;
        data.assign(count,Entry{});
    }
    void clear() { std::fill(data.begin(),data.end(),Entry{}); }
    Entry& slot(uint64_t key) { return data[key&(data.size()-1)]; }
};
std::mutex OutputMutex;
void output(const std::string& line) {
    std::lock_guard<std::mutex> guard(OutputMutex);
    std::cout<<line<<std::endl;
}
struct Limits { int depth=64; uint64_t nodes=0; int64_t soft=0,hard=0; };
struct Control { std::atomic<bool> stop{false},infinite{false},ponder{false}; };

class Search {
    Board board;
    std::vector<uint64_t> history;
    Table& table;
    Control& control;
    Limits limits;
    std::chrono::steady_clock::time_point began=std::chrono::steady_clock::now();
    uint64_t nodes=0;
    bool aborted=false;
    uint32_t killers[MaxPly][2]{};
    int quietHistory[2][128][128]{};
    Move iterationMove;

    int64_t elapsed() const {
        return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count();
    }
    bool halt(bool force=false) {
        if(control.stop || (limits.nodes && nodes>=limits.nodes) ||
           ((force || (nodes&255)==0) && !control.ponder && limits.hard>0 && elapsed()>=limits.hard)) aborted=true;
        return aborted;
    }
    bool drawn() const {
        if(board.half>=100 || insufficient(board)) return true;
        if(history.empty()) return false;
        int repeats=0;
        size_t span=std::min(history.size(),size_t(board.half)+1);
        for(size_t i=history.size();i>history.size()-span;--i)
            if(history[i-1]==history.back() && ++repeats==3) return true;
        return false;
    }
    static int storeScore(int score,int ply) {
        if(score>Mate-MaxPly) return score+ply;
        if(score<-Mate+MaxPly) return score-ply;
        return score;
    }
    static int loadScore(int score,int ply) {
        if(score>Mate-MaxPly) return score-ply;
        if(score<-Mate+MaxPly) return score+ply;
        return score;
    }
    int priority(const Move& m,uint32_t best,int ply) const {
        if(m.pack()==best) return 2000000;
        int victim=(m.flags&EP) ? Pawn : std::abs(board.cells[m.to]);
        if(victim || m.promote) return 1000000+Values[victim]*16-Values[std::abs(board.cells[m.from])]+(m.promote ? Values[m.promote] : 0);
        if(m.pack()==killers[ply][0]) return 900000;
        if(m.pack()==killers[ply][1]) return 800000;
        return quietHistory[index(board.side)][m.from][m.to];
    }
    void order(std::vector<Move>& moves,uint32_t best,int ply) const {
        std::vector<std::pair<int,Move>> scores;
        scores.reserve(moves.size());
        for(const auto& m:moves) scores.push_back({priority(m,best,ply),m});
        std::stable_sort(scores.begin(),scores.end(),[](const auto& a,const auto& b) { return a.first>b.first; });
        for(size_t i=0;i<moves.size();++i) moves[i]=scores[i].second;
    }

    int quiet(int alpha,int beta,int ply) {
        ++nodes;
        if(halt()) return 0;
        bool inCheck=board.check();
        auto moves=board.legal(!inCheck);
        if(moves.empty() && (inCheck || !board.has_legal())) return inCheck ? -Mate+ply : 0;
        if(drawn()) return 0;
        if(ply>=MaxPly-1) return evaluate(board);
        if(!inCheck) {
            int stand=evaluate(board);
            if(stand>=beta) return stand;
            alpha=std::max(alpha,stand);
        }
        order(moves,0,ply);
        for(const auto& m:moves) {
            auto u=board.make(m); history.push_back(board.key());
            int score=-quiet(-beta,-alpha,ply+1);
            history.pop_back(); board.unmake(m,u);
            if(aborted) return 0;
            if(score>=beta) return score;
            alpha=std::max(alpha,score);
        }
        return alpha;
    }

    int negamax(int depth,int alpha,int beta,int ply) {
        if(depth<=0) return quiet(alpha,beta,ply);
        ++nodes;
        if(halt()) return 0;
        auto moves=board.legal();
        bool inCheck=board.check();
        if(moves.empty()) return inCheck ? -Mate+ply : 0;
        if(drawn()) return 0;
        if(ply>=MaxPly-1) return evaluate(board);
        if(inCheck && depth<12) ++depth;
        uint64_t key=board.key();
        Entry cached=table.slot(key);
        bool hit=cached.key==key && cached.depth>=0;
        // TT cutoffs are disabled after reversible moves: the same board can
        // have different repetition history even with identical halfmove count.
        if(hit && ply>0 && board.half==0 && cached.half==0 && cached.depth>=depth) {
            int value=loadScore(cached.score,ply);
            if(cached.bound==1 || (cached.bound==2 && value>=beta) || (cached.bound==3 && value<=alpha)) return value;
        }
        order(moves,hit ? cached.move : 0,ply);
        int originalAlpha=alpha,best=-Infinity,number=0;
        Move selected;
        for(const auto& m:moves) {
            bool tactical=board.cells[m.to] || m.promote || (m.flags&EP);
            auto u=board.make(m); history.push_back(board.key());
            int score;
            if(number==0) score=-negamax(depth-1,-beta,-alpha,ply+1);
            else {
                int reduction=depth>=3 && number>=4 && !tactical && !inCheck && !board.check() ? 1 : 0;
                if(reduction && depth>=6 && number>=10) ++reduction;
                score=-negamax(depth-1-reduction,-alpha-1,-alpha,ply+1);
                if(score>alpha && reduction) score=-negamax(depth-1,-alpha-1,-alpha,ply+1);
                if(score>alpha && score<beta) score=-negamax(depth-1,-beta,-alpha,ply+1);
            }
            history.pop_back(); board.unmake(m,u);
            if(aborted) return 0;
            ++number;
            if(score>best) { best=score; selected=m; if(ply==0) iterationMove=m; }
            alpha=std::max(alpha,score);
            if(alpha>=beta) {
                if(!tactical) {
                    if(killers[ply][0]!=m.pack()) { killers[ply][1]=killers[ply][0]; killers[ply][0]=m.pack(); }
                    int& value=quietHistory[index(board.side)][m.from][m.to];
                    value=std::min(50000,value+depth*depth);
                }
                break;
            }
        }
        Entry& entry=table.slot(key);
        entry.key=key; entry.move=selected.pack(); entry.depth=int8_t(std::min(depth,127));
        entry.score=int16_t(storeScore(best,ply)); entry.half=uint8_t(std::min(board.half,255));
        entry.bound=best<=originalAlpha ? 3 : best>=beta ? 2 : 1;
        return best;
    }

    std::string pv(Move first,int depth) {
        Board temporary=board;
        std::vector<uint64_t> seen;
        std::string text;
        for(int i=0;i<depth && i<MaxPly;++i) {
            auto moves=temporary.legal();
            auto found=std::find(moves.begin(),moves.end(),first);
            if(found==moves.end()) break;
            text+=' '+found->uci();
            temporary.make(*found);
            uint64_t key=temporary.key();
            if(std::find(seen.begin(),seen.end(),key)!=seen.end()) break;
            seen.push_back(key);
            Entry entry=table.slot(key);
            if(entry.key!=key || !entry.move) break;
            auto next=temporary.legal();
            auto choice=std::find_if(next.begin(),next.end(),[&](const Move& m) { return m.pack()==entry.move; });
            if(choice==next.end()) break;
            first=*choice;
        }
        return text;
    }
public:
    Search(Board b,std::vector<uint64_t> h,Table& t,Control& c,Limits l):
        board(std::move(b)),history(std::move(h)),table(t),control(c),limits(l) {}

    void run() {
        auto moves=board.legal();
        Move chosen=moves.empty() ? Move{} : moves.front();
        int previous=0;
        for(int depth=1;depth<=limits.depth && !moves.empty();++depth) {
            if(halt(true)) break;
            int radius=depth>=4 ? 35 : Infinity;
            int alpha=std::max(-Infinity,previous-radius),beta=std::min(Infinity,previous+radius),score=0;
            while(true) {
                iterationMove=chosen;
                score=negamax(depth,alpha,beta,0);
                if(aborted) break;
                if(score>alpha && score<beta) break;
                if(alpha==-Infinity && beta==Infinity) break;
                radius=std::min(Infinity,radius*2);
                alpha=std::max(-Infinity,score-radius); beta=std::min(Infinity,score+radius);
            }
            if(aborted) break;
            chosen=iterationMove; previous=score;
            std::ostringstream info;
            info<<"info depth "<<depth<<" score ";
            if(std::abs(score)>Mate-MaxPly) info<<"mate "<<(score<0 ? -1 : 1)*((Mate-std::abs(score)+1)/2);
            else info<<"cp "<<score;
            info<<" nodes "<<nodes<<" time "<<elapsed()<<" nps "<<(nodes*1000/uint64_t(std::max<int64_t>(1,elapsed())))
                <<" pv"<<pv(chosen,depth);
            output(info.str());
            if(!control.infinite && !control.ponder && limits.soft>0 && elapsed()>=limits.soft) break;
            if(std::abs(score)>Mate-MaxPly && depth>=Mate-std::abs(score)) break;
        }
        // Explicit infinite/ponder mode holds even if a node/depth limit ended
        // computation. Only stop/ponderhit releases the completed result.
        while(!control.stop && (control.infinite || control.ponder))
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        output("bestmove "+chosen.uci());
    }
};

class Engine {
    Board board;
    std::vector<uint64_t> history;
    Table table;
    Control control;
    std::thread worker;
    int overhead=30;
    void stop() {
        control.stop=true;
        if(worker.joinable()) worker.join();
    }
    void position(std::istringstream& in) {
        stop();
        std::string token,fen;
        in>>token;
        if(token=="startpos") { fen=Start; in>>token; }
        else if(token=="fen") {
            for(int i=0;i<6;++i) {
                if(!(in>>token)) { output("info string invalid FEN"); return; }
                if(i) fen+=' ';
                fen+=token;
            }
            in>>token;
        } else return;
        Board next;
        if(!next.load(fen)) { output("info string invalid FEN"); return; }
        std::vector<uint64_t> keys{next.key()};
        if(token=="moves") while(in>>token) {
            auto moves=next.legal();
            auto found=std::find_if(moves.begin(),moves.end(),[&](const Move& m) { return m.uci()==token; });
            if(found==moves.end()) { output("info string illegal position move "+token); return; }
            next.make(*found); keys.push_back(next.key());
        }
        board=next; history=std::move(keys);
    }
    void go(std::istringstream& in) {
        stop();
        Limits limits;
        int64_t white=-1,black=-1,winc=0,binc=0,movetime=-1,movesToGo=0;
        bool infinite=false,ponder=false;
        std::string token;
        while(in>>token) {
            if(token=="infinite") infinite=true;
            else if(token=="ponder") ponder=true;
            else if(token=="wtime") in>>white;
            else if(token=="btime") in>>black;
            else if(token=="winc") in>>winc;
            else if(token=="binc") in>>binc;
            else if(token=="movetime") in>>movetime;
            else if(token=="movestogo") in>>movesToGo;
            else if(token=="depth") { in>>limits.depth; limits.depth=std::clamp(limits.depth,1,MaxPly-2); }
            else if(token=="nodes") in>>limits.nodes;
            else if(token=="perft") {
                int depth=0; in>>depth;
                if(depth>=0 && depth<=8) output("info string perft "+std::to_string(perft(board,depth)));
                return;
            }
        }
        if(!infinite) {
            int64_t remaining=board.side==1 ? white : black,inc=board.side==1 ? winc : binc;
            if(movetime>=0) limits.soft=limits.hard=std::max<int64_t>(1,movetime-overhead);
            else if(remaining>=0) {
                int64_t available=std::max<int64_t>(1,remaining-overhead);
                limits.soft=std::min(available,std::max<int64_t>(1,remaining/(movesToGo>0 ? movesToGo : 26)+inc*3/4));
                limits.hard=std::min(available,std::max<int64_t>(1,std::min(available/2,limits.soft*3)));
                limits.soft=std::min(limits.soft,limits.hard);
            }
        }
        control.stop=false; control.infinite=infinite; control.ponder=ponder;
        worker=std::thread([this,limits]() { Search search(board,history,table,control,limits); search.run(); });
    }
public:
    Engine() { board.load(Start); history.push_back(board.key()); table.resize(64); }
    ~Engine() { stop(); }
    void loop() {
        std::string line;
        while(std::getline(std::cin,line)) {
            std::istringstream in(line);
            std::string command; in>>command;
            if(command=="uci") {
                output("id name WetMeat Independent 0.2 experimental");
                output("id author WetMeat project");
                output("option name Hash type spin default 64 min 1 max 512");
                output("option name Threads type spin default 1 min 1 max 1");
                output("option name Move Overhead type spin default 30 min 0 max 1000");
                output("option name Clear Hash type button"); output("uciok");
            } else if(command=="isready") output("readyok");
            else if(command=="stop") stop();
            else if(command=="quit") { stop(); break; }
            else if(command=="ponderhit") control.ponder=false;
            else if(command=="ucinewgame") { stop(); table.clear(); }
            else if(command=="position") position(in);
            else if(command=="go") go(in);
            else if(command=="d") { stop(); output("info string FEN "+board.fen()); }
            else if(command=="setoption") {
                stop();
                std::string token,name,value; in>>token;
                while(in>>token && token!="value") { if(!name.empty()) name+=' '; name+=token; }
                std::getline(in,value);
                try {
                    if(name=="Hash") table.resize(std::clamp(std::stoi(value),1,512));
                    else if(name=="Move Overhead") overhead=std::clamp(std::stoi(value),0,1000);
                    else if(name=="Clear Hash") table.clear();
                } catch(const std::exception&) { output("info string invalid option value"); }
            }
        }
    }
};

} // namespace wetmeat

int main(int argc,char** argv) {
    using namespace wetmeat;
    if(argc>1) {
        std::string command=argv[1];
        if(command=="--legal-batch") {
            std::string fen;
            while(std::getline(std::cin,fen)) {
                Board board;
                if(!board.load(fen)) { std::cerr<<"Invalid FEN\n"; return 2; }
                auto moves=board.legal();
                for(size_t i=0;i<moves.size();++i) std::cout<<(i ? " " : "")<<moves[i].uci();
                std::cout<<'\n';
            }
            return 0;
        }
        if(command=="--perft" && argc>=3) {
            Board board;
            if(!board.load(argc>=4 ? argv[3] : Start)) return 2;
            int depth=0;
            try { depth=std::stoi(argv[2]); } catch(...) { return 2; }
            if(depth<0 || depth>8) return 2;
            std::cout<<perft(board,depth)<<'\n'; return 0;
        }
        if(command=="--key" && argc>=3) {
            Board board;
            if(!board.load(argv[2])) return 2;
            std::cout<<board.key()<<'\n'; return 0;
        }
        std::cerr<<"Usage: wetmeat [--perft depth [FEN] | --legal-batch | --key FEN]\n";
        return 2;
    }
    Engine engine;
    engine.loop();
    return 0;
}
