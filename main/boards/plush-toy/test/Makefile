# 主机端测试。eye_renderer / overlay_qr 是不接触硬件的纯计算模块，
# 可在开发机上直接编译运行，无需 ESP-IDF、无需烧录。
#
# 本目录不会被固件构建收录：main/CMakeLists.txt:869 的 glob 是
# boards/${BOARD_DIR}/*.cc，不递归子目录。
CXX ?= g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -I.. -Istubs

.PHONY: test clean

test: test_eye_renderer test_overlay_qr test_overlay_renderer test_pca9685
	./test_eye_renderer
	./test_overlay_qr
	./test_overlay_renderer
	./test_pca9685

test_eye_renderer: test_eye_renderer.cc ../eye_renderer.cc ../eye_renderer.h
	$(CXX) $(CXXFLAGS) -o $@ test_eye_renderer.cc ../eye_renderer.cc -lm

test_overlay_qr: test_overlay_qr.cc ../overlay_qr.cc ../qrcodegen.c ../overlay_qr.h ../qrcodegen.h
	$(CXX) $(CXXFLAGS) -x c++ -o $@ test_overlay_qr.cc ../overlay_qr.cc ../qrcodegen.c -lm

test_overlay_renderer: test_overlay_renderer.cc ../overlay_renderer.cc ../overlay_renderer.h
	$(CXX) $(CXXFLAGS) -o $@ test_overlay_renderer.cc ../overlay_renderer.cc -lm

test_pca9685: test_pca9685.cc ../pca9685.cc ../pca9685.h
	$(CXX) $(CXXFLAGS) -o $@ test_pca9685.cc ../pca9685.cc

clean:
	rm -f test_eye_renderer test_overlay_qr test_overlay_renderer test_pca9685 *.ppm
