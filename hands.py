import subprocess
import pyperclip
import time
import threading
from datetime import datetime
from pynput.keyboard import Key, Listener

# --- Try Import Windows Notifications ---
try:
    from win10toast import ToastNotifier
    toaster = ToastNotifier()
    NOTIFICATIONS_ENABLED = True
except ImportError:
    NOTIFICATIONS_ENABLED = False
    print("[WARNING] win10toast not found. Notifications disabled.")

# --- Configuration ---
TOGGLE_KEY = Key.f5
MAX_CLIP_LENGTH = 500
SAFE_MODE = True  # Enforces confirmation prompt
APP_NAME = "AI Hands Monitor"

# --- Global State ---
class State:
    active = False  # Starts dormant
    lock = threading.Lock()

state = State()

def send_notification(title, message, duration=5):
    """Sends a Windows toast notification if enabled."""
    if NOTIFICATIONS_ENABLED:
        try:
            # Run in a separate thread to avoid blocking the main loop
            threading.Thread(target=toaster.show_toast, args=(title, message, None, duration), daemon=True).start()
        except Exception:
            pass

def listen_for_hotkeys():
    """Listens for F5 press to toggle active state."""
    def on_press(key):
        try:
            if key == TOGGLE_KEY:
                with state.lock:
                    state.active = not state.active
                    is_active = state.active
                
                status = "ACTIVE" if is_active else "DORMANT"
                msg = f"System is now {status}"
                print(f"\n[TOGGLE] System state → {status}\n")
                
                # Notify
                send_notification(APP_NAME, msg, duration=3)
        except AttributeError:
            pass

    with Listener(on_press=on_press) as listener:
        listener.join()

def run_command(cmd):
    # --- Guardrail: Confirmation Prompt ---
    if SAFE_MODE:
        # Notify user that confirmation is needed
        send_notification(APP_NAME, "Confirmation Required", duration=2)
        confirm = input("\n[GUARDRAIL] Execute this command? (y/n): ").strip().lower()
        if confirm != 'y':
            print("[ABORTED] User declined execution.")
            send_notification(APP_NAME, "Execution Aborted", duration=2)
            return False

    # Notify Start
    send_notification(APP_NAME, f"Running: {cmd[:30]}...", duration=3)
    print(f"\n[RUNNING] {cmd}")
    start_time = time.time()
    status = "FAILED"
    
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=120
        )
        end_time = time.time()
        duration = end_time - start_time
        
        output = result.stdout if result.stdout else ""
        errors = result.stderr if result.stderr else ""

        # Determine status
        if result.returncode == 0:
            status = "SUCCESS"
            icon = "✓"
        else:
            status = "ERROR"
            icon = "✗"

        # Build report
        report = f"COMMAND: {cmd}\n"
        report += f"TIME: {datetime.now().strftime('%H:%M:%S')}\n"
        report += f"DURATION: {duration:.2f}s\n"
        report += f"STATUS: {status}\n"
        report += "─" * 40 + "\n"
        if output:
            report += output
        if errors:
            report += f"\nSTDERR:\n{errors}"
        if not output and not errors:
            report += "(no output)"

        # Print
        if output:
            print(output)
        if errors:
            print(f"[STDERR] {errors}")
        if not output and not errors:
            print("[OK] No output.")
        
        print(f"[STATUS] {status} in {duration:.2f} seconds")

        # Copy result to clipboard
        pyperclip.copy(report)
        print("[COPIED] → now just Ctrl+V to paste back to me\n")

        # Notify Finish
        send_notification(APP_NAME, f"{icon} {status} ({duration:.2f}s)", duration=5)
        return True

    except subprocess.TimeoutExpired:
        print("[TIMEOUT] Command exceeded 120s limit")
        send_notification(APP_NAME, "⚠ Timeout (120s)", duration=5)
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        send_notification(APP_NAME, f"⚠ System Error: {e}", duration=5)
        return False

def main():
    print("=" * 50)
    print("  AI HANDS — Notification Enabled")
    print("=" * 50)
    print("")
    print(f"[HOTKEY] Press {TOGGLE_KEY} to toggle ACTIVE/DORMANT")
    print("[STATUS] Currently: DORMANT (Press F5 to start)")
    print("[GUARD] Confirmation required before execution")
    print("")
    
    # Notify Startup
    send_notification(APP_NAME, "Script Started. Press F5.", duration=3)

    # Start hotkey listener in background
    listener_thread = threading.Thread(target=listen_for_hotkeys, daemon=True)
    listener_thread.start()

    last_clip = pyperclip.paste().strip() if pyperclip.paste() else ""

    while True:
        try:
            # Check state
            with state.lock:
                is_active = state.active
            
            if not is_active:
                time.sleep(0.5)
                continue

            clip = pyperclip.paste().strip()

            # Skip if same or empty or too long
            if clip == last_clip or not clip or len(clip) > MAX_CLIP_LENGTH:
                time.sleep(0.3)
                continue

            last_clip = clip

            # Check if it looks like a command
            lines = clip.split("\n")
            cmd = lines[0].strip()

            # Strip markdown code fences
            if cmd.startswith("```"):
                continue

            # Skip obvious non-commands (long English text)
            words = cmd.split()
            if len(words) > 20 and not any(cmd.startswith(p) for p in ("python", "pip", "dir", "type", "cd", "mkdir", "echo", "ls", "cat")):
                continue

            print(f"\n{'='*50}")
            print(f"[CLIPBOARD] {cmd[:80]}")
            
            # Notify Detection
            send_notification(APP_NAME, "Command Detected", duration=2)
            
            run_command(cmd)

            # Update last_clip to avoid re-triggering immediately
            time.sleep(1) 

        except KeyboardInterrupt:
            print("\nBye!")
            send_notification(APP_NAME, "Script Stopped", duration=2)
            break
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(0.5)

if __name__ == "__main__":
    main()