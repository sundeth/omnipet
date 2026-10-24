"""
DCom connection dialog UI component.
Handles device selection and protocol configuration.
"""

import pygame
from typing import Optional, Callable
from ui.ui_manager import UIManager
from ui.components.label import Label
from battle.dcom.dcom_controller import DComController, SERIAL_AVAILABLE
from battle.dcom.dcom_protocol import ProtocolType
from core import runtime_globals


class DComDialog:
    """
    Dialog for connecting to DCom device and selecting protocol.
    """
    
    def __init__(self, ui_manager: UIManager, on_connected: Optional[Callable] = None):
        self.ui_manager = ui_manager
        self.on_connected = on_connected
        self.controller = DComController()
        
        self.active = False
        self.state = "detecting"  # detecting, device_list, protocol_list, connecting, connected, error
        self.devices = []
        self.selected_device_idx = 0
        self.selected_protocol_idx = 0
        self.error_message = ""
        
        # UI elements
        self.labels = []
        self.buttons = []
        
        # Background overlay
        self.overlay = pygame.Surface((runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT))
        self.overlay.fill((0, 0, 0))
        self.overlay.set_alpha(180)
        
        # Dialog box
        self.dialog_width = 400
        self.dialog_height = 300
        self.dialog_x = (runtime_globals.SCREEN_WIDTH - self.dialog_width) // 2
        self.dialog_y = (runtime_globals.SCREEN_HEIGHT - self.dialog_height) // 2
        self.dialog_rect = pygame.Rect(self.dialog_x, self.dialog_y, self.dialog_width, self.dialog_height)
        
    def open(self):
        """Open the DCom dialog"""
        self.active = True
        self.state = "detecting"
        self.devices = []
        self.error_message = ""
        
        if not SERIAL_AVAILABLE:
            self.state = "error"
            self.error_message = "pyserial not installed.\nInstall with: pip install pyserial"
            return
        
        # Scan for devices
        self._detect_devices()
    
    def close(self):
        """Close the dialog"""
        self.active = False
        self.state = "detecting"
    
    def _detect_devices(self):
        """Detect available DCom devices"""
        self.devices = self.controller.find_dcom_devices()
        
        if not self.devices:
            self.state = "error"
            self.error_message = "No DCom devices found.\nCheck USB connection."
        else:
            self.state = "device_list"
            self.selected_device_idx = 0
    
    def _connect_device(self):
        """Connect to selected device"""
        if not self.devices:
            return
        
        self.state = "connecting"
        port, _ = self.devices[self.selected_device_idx]
        
        if self.controller.connect(port):
            self.controller.initialize_device()
            self.state = "protocol_list"
            self.selected_protocol_idx = 0
        else:
            self.state = "error"
            self.error_message = f"Failed to connect to {port}"
    
    def _select_protocol(self):
        """Complete connection with selected protocol"""
        protocols = DComController.get_protocol_list()
        if 0 <= self.selected_protocol_idx < len(protocols):
            protocol = protocols[self.selected_protocol_idx]
            
            # Test connection
            if self.controller.test_connection():
                self.state = "connected"
                
                # Callback with controller and protocol
                if self.on_connected:
                    self.on_connected(self.controller, protocol)
            else:
                self.state = "error"
                self.error_message = "Device not responding"
    
    def handle_event(self, event):
        """Handle input events"""
        if not self.active:
            return
        
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                
            elif self.state == "device_list":
                if event.key == pygame.K_UP:
                    self.selected_device_idx = (self.selected_device_idx - 1) % len(self.devices)
                elif event.key == pygame.K_DOWN:
                    self.selected_device_idx = (self.selected_device_idx + 1) % len(self.devices)
                elif event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                    self._connect_device()
                    
            elif self.state == "protocol_list":
                protocols = DComController.get_protocol_list()
                if event.key == pygame.K_UP:
                    self.selected_protocol_idx = (self.selected_protocol_idx - 1) % len(protocols)
                elif event.key == pygame.K_DOWN:
                    self.selected_protocol_idx = (self.selected_protocol_idx + 1) % len(protocols)
                elif event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                    self._select_protocol()
                    
            elif self.state == "connected":
                if event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                    self.close()
                    
            elif self.state == "error":
                if event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                    self.close()
    
    def draw(self, surface: pygame.Surface):
        """Draw the dialog"""
        if not self.active:
            return
        
        # Draw overlay
        surface.blit(self.overlay, (0, 0))
        
        # Draw dialog box
        pygame.draw.rect(surface, (40, 40, 60), self.dialog_rect)
        pygame.draw.rect(surface, (100, 100, 150), self.dialog_rect, 3)
        
        # Draw content based on state
        from utils.asset_utils import font_load
        from ui.ui_constants import TEXT_FONT
        from core import runtime_globals as _rg
        # The game's text font, scaled with the screen — these were pygame's
        # default face at a fixed size, which shrank away on large displays.
        font = font_load(TEXT_FONT, int(24 * _rg.UI_SCALE))
        small_font = font_load(TEXT_FONT, int(16 * _rg.UI_SCALE))
        
        if self.state == "detecting":
            self._draw_text(surface, font, "Detecting DCom devices...", 
                          self.dialog_x + self.dialog_width // 2, 
                          self.dialog_y + self.dialog_height // 2)
            
        elif self.state == "device_list":
            self._draw_device_list(surface, font, small_font)
            
        elif self.state == "protocol_list":
            self._draw_protocol_list(surface, font, small_font)
            
        elif self.state == "connecting":
            self._draw_text(surface, font, "Connecting...", 
                          self.dialog_x + self.dialog_width // 2,
                          self.dialog_y + self.dialog_height // 2)
            
        elif self.state == "connected":
            self._draw_text(surface, font, "Connected!", 
                          self.dialog_x + self.dialog_width // 2,
                          self.dialog_y + self.dialog_height // 2 - 20)
            self._draw_text(surface, small_font, "Press Enter to continue", 
                          self.dialog_x + self.dialog_width // 2,
                          self.dialog_y + self.dialog_height // 2 + 20)
            
        elif self.state == "error":
            self._draw_error(surface, font, small_font)
    
    def _draw_device_list(self, surface, font, small_font):
        """Draw list of available devices"""
        # Title
        title = font.render("Select DCom Device", True, (255, 255, 255))
        title_rect = title.get_rect(centerx=self.dialog_x + self.dialog_width // 2, 
                                    top=self.dialog_y + 20)
        surface.blit(title, title_rect)
        
        # Device list
        y = self.dialog_y + 60
        for i, (port, desc) in enumerate(self.devices):
            color = (255, 255, 100) if i == self.selected_device_idx else (200, 200, 200)
            prefix = "> " if i == self.selected_device_idx else "  "
            
            text = small_font.render(f"{prefix}{port}", True, color)
            text_rect = text.get_rect(left=self.dialog_x + 20, top=y)
            surface.blit(text, text_rect)
            
            desc_text = small_font.render(desc[:40], True, (150, 150, 150))
            desc_rect = desc_text.get_rect(left=self.dialog_x + 30, top=y + 20)
            surface.blit(desc_text, desc_rect)
            
            y += 50
        
        # Instructions
        instr = small_font.render("↑↓ Navigate  Enter: Connect  Esc: Cancel", True, (150, 150, 150))
        instr_rect = instr.get_rect(centerx=self.dialog_x + self.dialog_width // 2,
                                    bottom=self.dialog_y + self.dialog_height - 10)
        surface.blit(instr, instr_rect)
    
    def _draw_protocol_list(self, surface, font, small_font):
        """Draw list of available protocols"""
        # Title
        title = font.render("Select Protocol", True, (255, 255, 255))
        title_rect = title.get_rect(centerx=self.dialog_x + self.dialog_width // 2,
                                    top=self.dialog_y + 20)
        surface.blit(title, title_rect)
        
        # Protocol list
        protocols = DComController.get_protocol_list()
        y = self.dialog_y + 60
        
        for i, protocol in enumerate(protocols):
            color = (255, 255, 100) if i == self.selected_protocol_idx else (200, 200, 200)
            prefix = "> " if i == self.selected_protocol_idx else "  "
            
            text = small_font.render(f"{prefix}{protocol.display_name}", True, color)
            text_rect = text.get_rect(left=self.dialog_x + 30, top=y)
            surface.blit(text, text_rect)
            
            y += 35
        
        # Instructions
        instr = small_font.render("↑↓ Navigate  Enter: Select  Esc: Cancel", True, (150, 150, 150))
        instr_rect = instr.get_rect(centerx=self.dialog_x + self.dialog_width // 2,
                                    bottom=self.dialog_y + self.dialog_height - 10)
        surface.blit(instr, instr_rect)
    
    def _draw_error(self, surface, font, small_font):
        """Draw error message"""
        # Title
        title = font.render("Error", True, (255, 100, 100))
        title_rect = title.get_rect(centerx=self.dialog_x + self.dialog_width // 2,
                                    top=self.dialog_y + 20)
        surface.blit(title, title_rect)
        
        # Error message (split into lines)
        lines = self.error_message.split('\n')
        y = self.dialog_y + 80
        for line in lines:
            text = small_font.render(line, True, (255, 200, 200))
            text_rect = text.get_rect(centerx=self.dialog_x + self.dialog_width // 2, top=y)
            surface.blit(text, text_rect)
            y += 25
        
        # Instructions
        instr = small_font.render("Press Enter to close", True, (150, 150, 150))
        instr_rect = instr.get_rect(centerx=self.dialog_x + self.dialog_width // 2,
                                    bottom=self.dialog_y + self.dialog_height - 10)
        surface.blit(instr, instr_rect)
    
    def _draw_text(self, surface, font, text, x, y):
        """Helper to draw centered text"""
        rendered = font.render(text, True, (255, 255, 255))
        rect = rendered.get_rect(center=(x, y))
        surface.blit(rendered, rect)
