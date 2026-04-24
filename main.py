"""
Verdant Wilds - 2D Top-Down RPG Survival Game
Entry point
"""

import pygame
import sys
from game import Game

def main():
    pygame.init()
    try:
        pygame.mixer.init()
    except pygame.error:
        # Audio should not prevent the game from starting.
        pass
    
    screen = pygame.display.set_mode((1280, 768))
    pygame.display.set_caption("Verdant Wilds")
    pygame.display.set_icon(pygame.Surface((32, 32)))
    
    clock = pygame.time.Clock()
    game = Game(screen, clock)
    game.run()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
