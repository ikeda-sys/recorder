# sin_reco_true_final.py (1時間ごとのファイル分割機能を無効化したバージョン)
# -*- coding: utf:8 -*-
import os
import sys
import time
import cv2
import numpy as np
from datetime import datetime, timedelta

PICAMERA_AVAILABLE = False
try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CRITICAL] Picamera2ライブラリが見つかりません。")
except Exception as e:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CRITICAL] カメラライブラリのインポート中にエラー: {e}")

OUTPUT_DIR_BASE = "/media/c1/FCB7-43FD1/録画データ"
# CHUNK_SECONDS = 3600 # 分割機能は使わないが、念のため残しておく
DEFAULT_PREVIEW_WIDTH = 800

quit_program = False

def draw_grid_on_image(image):
    height, width, _ = image.shape
    max_x, max_y = width - 1, height - 1
    line_color = (0, 255, 0)
    line_thickness = 2
    
    center_y, center_x = height // 2, width // 2
    
    cv2.line(image, (0, center_y), (max_x, center_y), line_color, line_thickness)
    cv2.line(image, (center_x, 0), (center_x, max_y), line_color, line_thickness)
    cv2.line(image, (0, 0), (max_x, max_y), line_color, line_thickness)
    cv2.line(image, (max_x, 0), (0, max_y), line_color, line_thickness)
    
    rect_w = int(width * 0.79576)
    rect_h = int(height * 0.840)
    pt1_x = center_x - rect_w // 2
    pt1_y = center_y - rect_h // 2
    pt2_x = center_x + rect_w // 2
    pt2_y = center_y + rect_h // 2
    cv2.rectangle(image, (pt1_x, pt1_y), (pt2_x, pt2_y), line_color, line_thickness)


def ensure_dir_exists(path):
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] ディレクトリ作成失敗 {path}: {e}")
            return False
    check_path = path if os.path.isdir(path) else os.path.dirname(path)
    if check_path and not os.access(check_path, os.W_OK):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] 書き込み権限なし: {check_path}")
        return False
    return True

def create_filename(output_base_dir):
    now = datetime.now()
    date_str = now.strftime('%Y_%m_%d')
    time_str = now.strftime("%H%M%S")
    base_filename_prefix = f'{date_str}_{time_str}'
    current_output_dir = os.path.join(output_base_dir, date_str)
    if not ensure_dir_exists(current_output_dir): return None
    filename = os.path.join(current_output_dir, f'{base_filename_prefix}.mp4')
    count = 1
    base_filename_for_unique_check = filename
    while os.path.exists(filename):
        name, ext = os.path.splitext(base_filename_for_unique_check)
        filename = f"{name}_{count:02d}{ext}"
        count += 1
        if count > 100:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WARNING] 同一時刻のファイル名が多数存在: {os.path.splitext(base_filename_for_unique_check)[0]}")
            return None
    return filename

def main():
    global quit_program
    if len(sys.argv) != 5:
        print("使い方: python <script_name>.py <継続時間(ms)> <fps> <録画サイズ(hd/qhd)> <プレビュー(on/off)>")
        sys.exit(1)
        
    try:
        total_duration_ms = int(sys.argv[1])
        target_fps = int(sys.argv[2])
        record_size_key = sys.argv[3].lower()
        initial_preview_on = sys.argv[4].lower() == 'on'
    except ValueError:
        print("[ERROR] 継続時間とFPSは整数で指定してください。")
        sys.exit(1)

    size_mapping = { "hd": (1280, 720), "qhd": (960, 540)}
    if record_size_key not in size_mapping:
        print("[ERROR] 録画サイズは  'hd', 'qhd', のいずれかで指定してください。")
        sys.exit(1)

    record_frame_size = size_mapping[record_size_key]
    if total_duration_ms <= 0 or target_fps <= 0:
        print("[ERROR] 継続時間とFPSは正の値である必要があります。")
        sys.exit(1)
    
    show_previews = initial_preview_on
    preview_states = {"Normal Preview": True, "Grid Preview": True}
    target_preview_width = min(record_frame_size[0], DEFAULT_PREVIEW_WIDTH)
    total_duration_sec = total_duration_ms / 1000.0

    print("\n--- 録画設定 ---")
    print(f"  録画時間: {total_duration_sec:.1f}秒 ({total_duration_ms}ms)")
    print(f"  フレームレート: {target_fps} FPS")
    print(f"  録画サイズ: {record_size_key.upper()} ({record_frame_size[0]}x{record_frame_size[1]})")
    print(f"  プレビュー幅(自動): {target_preview_width}px")
    print(f"  プレビュー初期状態: {'有効' if initial_preview_on else '無効'}")
    if show_previews:
        print("  操作キー: 'p'(全体), '1'(通常), '2'(グリッド), 'q'(終了)")
    print(f"  安全な終了方法: Ctrl+C")
    print(f"  保存先ベース: {OUTPUT_DIR_BASE}")
    print("----------------\n")
    if not ensure_dir_exists(OUTPUT_DIR_BASE):
        sys.exit(1)

    cam = None
    out = None
    filename = None # finallyで参照するため、ここで定義

    try:
        # === カメラ設定 (元の機能を維持) ===
        sensor_max_w, sensor_max_h = (3280, 2464)
        if PICAMERA_AVAILABLE:
            with Picamera2() as temp_cam:
                props = temp_cam.camera_properties
                if props and "PixelArraySize" in props:
                    sensor_max_w, sensor_max_h = props["PixelArraySize"]
        
        user_w_ratio, user_h_ratio = (4, 3)
        capture_h_base = 922 
        capture_w = int(capture_h_base * user_w_ratio / user_h_ratio)
        if capture_w > sensor_max_w:
            capture_w = sensor_max_w
            capture_h = int(capture_w * user_h_ratio / user_w_ratio)
        else:
            capture_h = capture_h_base
        capture_w = max(160, (capture_w // 2) * 2)
        capture_h = max(120, (capture_h // 2) * 2)
        dynamic_capture_frame_size = (capture_w, capture_h)
        
        rec_w, rec_h = record_frame_size
        aspect_ratio = rec_h / rec_w
        preview_w = target_preview_width
        preview_h = int(preview_w * aspect_ratio)
        preview_w = (preview_w // 2) * 2
        preview_h = (preview_h // 2) * 2
        current_preview_size = (preview_w, preview_h)
        
        if show_previews:
            print(f"  プレビュー基準解像度: {current_preview_size[0]}x{current_preview_size[1]}")
        
        cam = Picamera2()
        frame_duration_us = int(1_000_000 / target_fps)
        
        video_config = cam.create_video_configuration(
            main={'size': record_frame_size, 'format': 'XRGB8888'},
            raw={'size': dynamic_capture_frame_size},
            lores={'size': current_preview_size, 'format': 'YUV420'},
            controls={'FrameRate': float(target_fps), 'FrameDurationLimits': (frame_duration_us, frame_duration_us), 'AeEnable': True},
            queue=False, buffer_count=4)
        cam.configure(video_config)

        # === プレビューウィンドウの準備 (プレビューONの時のみ) ===
        if show_previews:
            cv2.namedWindow("Normal Preview", cv2.WINDOW_NORMAL)
            cv2.namedWindow("Grid Preview", cv2.WINDOW_NORMAL)
            normal_preview_pos, grid_preview_pos, offscreen_pos = (0, 50), (current_preview_size[0] + 10, 50), (-1000, -1000)
            def update_window_visibility():
                if show_previews and preview_states["Normal Preview"]: cv2.moveWindow("Normal Preview", normal_preview_pos[0], normal_preview_pos[1])
                else: cv2.moveWindow("Normal Preview", offscreen_pos[0], offscreen_pos[1])
                if show_previews and preview_states["Grid Preview"]: cv2.moveWindow("Grid Preview", grid_preview_pos[0], grid_preview_pos[1])
                else: cv2.moveWindow("Grid Preview", offscreen_pos[0], offscreen_pos[1])
            update_window_visibility()

        cam.start()
        rec_start_dt = datetime.now()
        rec_end_dt = rec_start_dt + timedelta(seconds=total_duration_sec)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] カメラ起動。録画を開始します。")

        # === ここから1時間ごとの分割機能を無効化するための修正 ===
        
        # 1. ファイル作成とVideoWriterの準備をループの前に一度だけ実行
        filename = create_filename(OUTPUT_DIR_BASE)
        if not filename:
            raise Exception("ファイル名の作成に失敗しました。") # エラーを発生させて終了
        
        out = cv2.VideoWriter(filename, cv2.VideoWriter_fourcc(*'mp4v'), target_fps, record_frame_size)
        if not out.isOpened():
            raise Exception(f"VideoWriterオープン失敗: {filename}")

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] 録画開始: {os.path.basename(filename)}")
        
        # 2. メインループを一つにまとめる
        last_ideal_time = time.monotonic()
        while datetime.now() < rec_end_dt and not quit_program:
            request = cam.capture_request()
            if not request: continue
            
            main_rgba = request.make_array('main')
            if main_rgba is not None:
                main_bgr = cv2.cvtColor(main_rgba, cv2.COLOR_BGRA2BGR)
                out.write(main_bgr)
            
            if show_previews:
                lores_yuv = request.make_array('lores')
                if lores_yuv is not None:
                    lores_bgr = cv2.cvtColor(lores_yuv, cv2.COLOR_YUV2BGR_I420)
                    lores_bgr = lores_bgr[0:current_preview_size[1], 0:current_preview_size[0]]
                    if preview_states["Normal Preview"]: cv2.imshow("Normal Preview", lores_bgr)
                    if preview_states["Grid Preview"]:
                        grid_img = lores_bgr.copy()
                        draw_grid_on_image(grid_img)
                        cv2.imshow("Grid Preview", grid_img)

            request.release()
            
            key = -1
            if show_previews: key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'): quit_program = True
            elif key == ord('p'):
                show_previews = not show_previews
                update_window_visibility()
            elif key == ord('1'):
                preview_states["Normal Preview"] = not preview_states["Normal Preview"]
                update_window_visibility()
            elif key == ord('2'):
                preview_states["Grid Preview"] = not preview_states["Grid Preview"]
                update_window_visibility()
            
            sleep_time = (last_ideal_time + (1.0 / target_fps)) - time.monotonic()
            if sleep_time > 0: time.sleep(sleep_time)
            last_ideal_time += (1.0 / target_fps)
    
    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] Ctrl+Cを検出。終了処理が実行されました。")
    
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CRITICAL] メイン処理で予期せぬエラー: {e}")

    finally:
        # === 最終クリーンアップ処理 ===
        # 3. 録画ファイルを一度だけ閉じる
        if out and out.isOpened():
            out.release()
            # filenameがNoneでないことを確認してから表示
            if filename:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] 録画ファイルを正常にクローズ: {os.path.basename(filename)}")
        
        if cam and cam.started:
            cam.stop()
        if show_previews:
            cv2.destroyAllWindows()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] プログラム終了。")


if __name__ == '__main__':
    if not PICAMERA_AVAILABLE:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CRITICAL] Picamera2利用不可。終了します。")
    else:
        main()