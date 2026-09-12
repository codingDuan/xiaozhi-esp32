# 主机端测试。eye_renderer / overlay_qr 是不接触硬件的纯计算模块，
# 可在开发机上直接编译运行，无需 ESP-IDF、无需烧录。
#
# 本目录不会被固件构建收录：main/CMakeLists.txt:869 的 glob 是
# boards/${BOARD_DIR}/*.cc，不递归子目录。
CXX ?= g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -I.. -Istubs

.PHONY: test clean preview-png

test: test_eye_renderer test_eye_theme test_overlay_qr test_overlay_renderer test_pca9685 test_http_channel test_mpr121 test_touch_controller test_mpu6050 test_motion_controller test_gesture_policy
	./test_eye_renderer
	./test_eye_theme
	./test_overlay_qr
	./test_overlay_renderer
	./test_pca9685
	./test_http_channel
	./test_mpr121
	./test_touch_controller
	./test_mpu6050
	./test_motion_controller
	./test_gesture_policy

test_eye_renderer: test_eye_renderer.cc ../eye_renderer.cc ../eye_renderer.h ../eye_theme.cc ../eye_theme.h ../eye_iris_tex.cc ../eye_iris_tex.h
	$(CXX) $(CXXFLAGS) -o $@ test_eye_renderer.cc ../eye_renderer.cc ../eye_theme.cc ../eye_iris_tex.cc -lm

test_eye_theme: test_eye_theme.cc ../eye_theme.cc ../eye_theme.h ../eye_iris_tex.cc
	$(CXX) $(CXXFLAGS) -o $@ test_eye_theme.cc ../eye_theme.cc ../eye_iris_tex.cc

test_overlay_qr: test_overlay_qr.cc ../overlay_qr.cc ../qrcodegen.c ../overlay_qr.h ../qrcodegen.h
	$(CXX) $(CXXFLAGS) -x c++ -o $@ test_overlay_qr.cc ../overlay_qr.cc ../qrcodegen.c -lm

test_overlay_renderer: test_overlay_renderer.cc ../overlay_renderer.cc ../overlay_renderer.h
	$(CXX) $(CXXFLAGS) -o $@ test_overlay_renderer.cc ../overlay_renderer.cc -lm

test_pca9685: test_pca9685.cc ../pca9685.cc ../pca9685.h
	$(CXX) $(CXXFLAGS) -o $@ test_pca9685.cc ../pca9685.cc

test_http_channel: test_http_channel.cc ../test_http_channel.cc ../test_http_channel.h
	$(CXX) $(CXXFLAGS) -o $@ test_http_channel.cc ../test_http_channel.cc

test_touch_controller: test_touch_controller.cc ../touch_controller.cc ../touch_controller.h ../mpr121.cc ../mpr121.h ../config.h
	$(CXX) $(CXXFLAGS) -o $@ test_touch_controller.cc ../touch_controller.cc ../mpr121.cc

test_motion_controller: test_motion_controller.cc ../motion_controller.cc ../motion_controller.h ../mpu6050.cc ../mpu6050.h ../config.h
	$(CXX) $(CXXFLAGS) -o $@ test_motion_controller.cc ../motion_controller.cc ../mpu6050.cc

test_mpu6050: test_mpu6050.cc ../mpu6050.cc ../mpu6050.h ../config.h
	$(CXX) $(CXXFLAGS) -o $@ test_mpu6050.cc ../mpu6050.cc

# 纯头文件模块，不链接任何 .cc；-I../../.. 只为拿到 main/device_state.h
test_gesture_policy: test_gesture_policy.cc ../gesture_policy.h ../gesture.h ../config.h
	$(CXX) $(CXXFLAGS) -I../../.. -o $@ test_gesture_policy.cc

test_mpr121: test_mpr121.cc ../mpr121.cc ../mpr121.h ../config.h
	$(CXX) $(CXXFLAGS) -o $@ test_mpr121.cc ../mpr121.cc

preview: preview.cc ../eye_renderer.cc ../eye_renderer.h ../eye_theme.cc ../eye_theme.h ../eye_iris_tex.cc
	$(CXX) $(CXXFLAGS) -o $@ preview.cc ../eye_renderer.cc ../eye_theme.cc ../eye_iris_tex.cc -lm

# 肉眼检查用：把 THEMES 里每个主题的七种情绪渲成 PNG
THEMES ?= ocean anime-sky
preview-png: preview
	./preview $(THEMES)
	python3 to_png.py

clean:
	rm -f test_eye_renderer test_eye_theme test_overlay_qr test_overlay_renderer test_pca9685 test_http_channel test_mpr121 test_touch_controller test_mpu6050 test_motion_controller test_gesture_policy preview *.ppm
