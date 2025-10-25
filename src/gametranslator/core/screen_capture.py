"""
Screen capture module for GameTranslator.
"""

import cv2
import numpy as np
from PIL import Image, ImageGrab


class ScreenCapture:
    """Handles screen capture functionality."""

    @staticmethod
    def capture_screen(region=None):
        """
        Capture the screen or a region of the screen.

        Args:
            region (tuple, optional): Region to capture (left, top, width, height).
                                     If None, captures the entire screen.

        Returns:
            PIL.Image: The captured image.
        """
        if region:
            left, top, width, height = region
            bbox = (left, top, left + width, top + height)
            screenshot = ImageGrab.grab(bbox=bbox, all_screens=True)
        else:
            screenshot = ImageGrab.grab(all_screens=True)

        return screenshot
    
    @staticmethod
    def capture_to_cv2(region=None):
        """
        Capture the screen and convert to OpenCV format.
        
        Args:
            region (tuple, optional): Region to capture (left, top, width, height).
        
        Returns:
            numpy.ndarray: The captured image in OpenCV format (BGR).
        """
        screenshot = ScreenCapture.capture_screen(region)
        # Convert PIL Image to OpenCV format (RGB to BGR)
        cv_image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        return cv_image
    
    @staticmethod
    def save_capture(image, filepath):
        """
        Save a captured image to file.
        
        Args:
            image (PIL.Image or numpy.ndarray): The image to save.
            filepath (str): Path to save the image.
        """
        if isinstance(image, np.ndarray):
            # Convert OpenCV image to PIL
            image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        
        image.save(filepath)