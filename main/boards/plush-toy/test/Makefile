# 主机端测试。eye_renderer / overlay_qr 是不接触硬件的纯计算模块，
# 可在开发机上直接编译运行，无需 ESP-IDF、无需烧录。
#
# 本目录不会被固件构建收录：main/CMakeLists.txt:869 的 glob 是
# boards/${BOARD_DIR}/*.cc，不递归子目录。
CXX ?= g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -I..

.PHONY: test clean

test: test_eye_renderer
	./test_eye_renderer

test_eye_renderer: test_eye_renderer.cc ../eye_renderer.cc ../eye_renderer.h
	$(CXX) $(CXXFLAGS) -o $@ test_eye_renderer.cc ../eye_renderer.cc -lm

clean:
	rm -f test_eye_renderer test_overlay_qr *.ppm
