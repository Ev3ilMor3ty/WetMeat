CXX ?= c++
CPPFLAGS += -Isrc -MMD -MP
CXXFLAGS ?= -O3 -DNDEBUG
CXXFLAGS += -std=c++20 -Wall -Wextra -Wpedantic -pthread
LDFLAGS += -pthread
BUILD ?= build
CORE_SOURCES = src/chess.cpp src/neural.cpp src/evaluate.cpp src/search.cpp
CORE_OBJECTS = $(CORE_SOURCES:src/%.cpp=$(BUILD)/%.o)

.PHONY: all test extended-test clean native portable sanitize thread-sanitize
all: $(BUILD)/aurora

$(BUILD)/aurora: $(CORE_OBJECTS) $(BUILD)/main.o
	$(CXX) $^ $(LDFLAGS) -o $@

$(BUILD)/core-tests: $(CORE_OBJECTS) $(BUILD)/core_tests.o
	$(CXX) $^ $(LDFLAGS) -o $@

$(BUILD)/%.o: src/%.cpp
	@mkdir -p $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD)/core_tests.o: tests/core_tests.cpp
	@mkdir -p $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

test: $(BUILD)/aurora $(BUILD)/core-tests
	$(BUILD)/core-tests
	python3 tests/test_uci.py --engine $(BUILD)/aurora

extended-test: $(BUILD)/aurora $(BUILD)/core-tests
	$(BUILD)/core-tests --extended
	python3 tests/test_uci.py --engine $(BUILD)/aurora

native:
	$(MAKE) BUILD=build-native CXXFLAGS='-O3 -DNDEBUG -std=c++20 -Wall -Wextra -Wpedantic -pthread -march=native' all

portable:
	$(MAKE) BUILD=build-portable LDFLAGS='-pthread -static-libstdc++ -static-libgcc' all

sanitize:
	$(MAKE) BUILD=build-sanitize CXXFLAGS='-O1 -g -std=c++20 -Wall -Wextra -Wpedantic -pthread -fsanitize=address,undefined -fno-omit-frame-pointer' LDFLAGS='-pthread -fsanitize=address,undefined' extended-test

thread-sanitize:
	$(MAKE) BUILD=build-tsan CXXFLAGS='-O1 -g -std=c++20 -Wall -Wextra -Wpedantic -pthread -fsanitize=thread -fno-omit-frame-pointer' LDFLAGS='-pthread -fsanitize=thread' test

clean:
	rm -rf $(BUILD)

-include $(wildcard $(BUILD)/*.d)
