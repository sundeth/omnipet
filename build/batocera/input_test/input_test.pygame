import time

# --- GPIO Test ---
try:
    from gpiozero import Button
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False

button_pins = [16, 5, 13, 6, 26, 19, 21, 20, 15, 12, 14, 23]
if HAS_GPIO:
    buttons = {pin: Button(pin, pull_up=True, bounce_time=0.05) for pin in button_pins}

    def button_pressed(pin):
        print(f"GPIO {pin} PRESSED!")
        last_events.append(f"GPIO {pin} PRESSED!")

    def button_released(pin):
        print(f"GPIO {pin} RELEASED!")
        last_events.append(f"GPIO {pin} RELEASED!")

    for pin, button in buttons.items():
        button.when_pressed = lambda pin=pin: button_pressed(pin)
        button.when_released = lambda pin=pin: button_released(pin)

# --- Pygame Test for Keyboard, Mouse, Joystick ---
import pygame

pygame.init()
screen = pygame.display.set_mode((500, 250))
pygame.display.set_caption("Input Test")
font = pygame.font.SysFont(None, 28)

# Joystick setup
pygame.joystick.init()
for i in range(pygame.joystick.get_count()):
    joy = pygame.joystick.Joystick(i)
    joy.init()
    print(f"Detected joystick: {joy.get_name()} ({joy.get_numaxes()} axes, {joy.get_numbuttons()} buttons)")

print("Press keys, mouse buttons, joystick buttons/axes/hats, or GPIO buttons (if available).")

last_events = []

def draw_events(surface, events):
    surface.fill((30, 30, 30))
    y = 10
    for event in events[-8:]:  # Show last 8 events
        txt = font.render(event, True, (255, 255, 255))
        surface.blit(txt, (10, y))
        y += 28
    pygame.display.flip()

try:
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise KeyboardInterrupt
            elif event.type == pygame.KEYDOWN:
                msg = f"KEYDOWN: {pygame.key.name(event.key)}"
                print(msg)
                last_events.append(msg)
            elif event.type == pygame.KEYUP:
                msg = f"KEYUP: {pygame.key.name(event.key)}"
                print(msg)
                last_events.append(msg)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                msg = f"MOUSEBUTTONDOWN: button {event.button} at {event.pos}"
                print(msg)
                last_events.append(msg)
            elif event.type == pygame.MOUSEBUTTONUP:
                msg = f"MOUSEBUTTONUP: button {event.button} at {event.pos}"
                print(msg)
                last_events.append(msg)
            elif event.type == pygame.JOYBUTTONDOWN:
                msg = f"JOYBUTTONDOWN: joystick {event.joy} button {event.button}"
                print(msg)
                last_events.append(msg)
            elif event.type == pygame.JOYBUTTONUP:
                msg = f"JOYBUTTONUP: joystick {event.joy} button {event.button}"
                print(msg)
                last_events.append(msg)
            elif event.type == pygame.JOYAXISMOTION:
                msg = f"JOYAXISMOTION: joystick {event.joy} axis {event.axis} value {event.value:.3f}"
                print(msg)
                last_events.append(msg)
            elif event.type == pygame.JOYHATMOTION:
                msg = f"JOYHATMOTION: joystick {event.joy} hat {event.hat} value {event.value}"
                print(msg)
                last_events.append(msg)
        draw_events(screen, last_events)
        time.sleep(0.01)
except KeyboardInterrupt:
    print("Exited test script.")
    pygame.quit()