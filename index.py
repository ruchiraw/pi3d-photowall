#!/usr/bin/python3
"""
Simple Sprite objects fall across the screen and are moved back to the top once
they hit the bottom edge.
"""

import random, time, threading, math, datetime
import subprocess

import pi3d

from six_mod.moves import queue
from gpiozero import MotionSensor

import PhotoUtils

BACKGROUND = (0.0, 0.0, 0.0, 0.0)
DISPLAY = pi3d.Display.create(background=BACKGROUND, frames_per_second=60)
CAMERA = pi3d.Camera((0, 0, 0), (0, 0, -1), (1, 1000, 45.0, DISPLAY.width/DISPLAY.height), is_3d=False)
SHADER = pi3d.Shader('uv_flat')
# KEYBOARD = pi3d.Keyboard()

pir = MotionSensor(4)

PRELOAD_IMAGE_COUNT = 4

IMAGE_GAP = 150
TRANSITION_SPEED = 0.5

IMAGE_MAX_HEIGHT = 650
IMAGE_MAX_WIDTH = 900

RANDOMIZE_SIZES = True

PAUSE_WHEN_UNWATCHED = True
MIN_DURATION_WITHOUT_MOTION = 15 * 60

displayOn = True

photos = []
backgrounds = []

fileQ = queue.Queue()

nextPhotoIndex = 0
fileNames, numFiles = PhotoUtils.get_files(None, None)

lastMotionAt = datetime.datetime.now().timestamp()

def last_photo():
  if (len(photos) > 0):
    return photos[-1]

  return None

def randomize (ratio):
  if not RANDOMIZE_SIZES:
    return 0.9

  return random.randrange(80, 100, 10) / 100

def revised_sizes (img):
  w = img.width
  h = img.height

  if w > h:
    wr = randomize(IMAGE_MAX_WIDTH / w)
    if wr > 1:
      wr = 1
    return (wr * w, wr * h)
  else:
    hr = randomize(IMAGE_MAX_HEIGHT / h)
    if hr > 1:
      hr = 1
    return (hr * w, hr * h)

def tex_load():
  matter = PhotoUtils.get_matter(DISPLAY)

  while True:
    photoIndex = fileQ.get()

    last = last_photo()

    tex = PhotoUtils.tex_load(matter, photoIndex, fileNames)

    if tex is None:
      fileQ.task_done()
      continue

    texture, img = tex

    if texture is None or img is None:
      fileQ.task_done()
      continue

    width, height = revised_sizes(img)
    sprite = pi3d.ImageSprite(texture=texture, shader=SHADER, w=width, h=height, camera=CAMERA)

    if last is not None:
      sprite.positionX(last['sprite'].x() + last['width']/2 + IMAGE_GAP + width/2)
    else:
      sprite.positionX(DISPLAY.width)

    DISPLAY.add_sprites(sprite)

    photos.append({'sprite': sprite, 'width': width, 'height': height})

    fileQ.task_done()

def next_image():
  global nextPhotoIndex

  fileQ.put(nextPhotoIndex)
  nextPhotoIndex += 1

  if nextPhotoIndex >= len(fileNames):
    nextPhotoIndex = 0

def clear_image(photo):
  DISPLAY.remove_sprites(photo['sprite'])
  photos.remove(photo)

def animate_image(photo):
  photo['sprite'].translateX(-TRANSITION_SPEED)
  #CAMERA.offset((TRANSITION_SPEED, 0, 0))

def animate_background(background):
  background.translateX(-TRANSITION_SPEED)

def is_image_invisible(photo):
  is_invisible = photo['sprite'].x() + DISPLAY.width/2 + photo['width']/2 < 0  
  return is_invisible

def is_background_invisible(background):
  is_invisible = background.x() + DISPLAY.width < 0  
  return is_invisible

def boot():
  thread = threading.Thread(target=tex_load)
  thread.daemon = True
  thread.start()

  background_texture1 = PhotoUtils.background_texture(DISPLAY)
  background_texture2 = PhotoUtils.background_texture(DISPLAY)
  background_sprite1 = pi3d.ImageSprite(texture=background_texture1, shader=SHADER, w=DISPLAY.width, h=DISPLAY.height, z=2000, camera=CAMERA)
  background_sprite2 = pi3d.ImageSprite(texture=background_texture2, shader=SHADER, w=DISPLAY.width, h=DISPLAY.height, z=2000, camera=CAMERA)
  background_sprite2.translateX(DISPLAY.width)

  # background_sprite.draw()
  DISPLAY.add_sprites(background_sprite1)
  DISPLAY.add_sprites(background_sprite2)

  backgrounds.append(background_sprite1)
  backgrounds.append(background_sprite2)

  for b in range(PRELOAD_IMAGE_COUNT):
    next_image()

def handle_keyboard_events():  
  k = KEYBOARD.read()
  if k >-1:
    if k == 27:
      KEYBOARD.close()
      DISPLAY.stop()
      return True

def turn_display_off():
  global displayOn

  if not displayOn:
    return

  # print('turn off display')
  subprocess.call('vcgencmd display_power 0', shell=True)
  displayOn = False

def turn_display_on():
  global displayOn

  if displayOn:
    return

  # print('turn on display')
  subprocess.call('vcgencmd display_power 1', shell=True)
  displayOn = True

def is_unwatched():
  if not PAUSE_WHEN_UNWATCHED:
    return False
  
  return datetime.datetime.now().timestamp() - lastMotionAt > MIN_DURATION_WITHOUT_MOTION

def display_images():
  global lastMotionAt
  
  if pir.motion_detected:
    lastMotionAt = datetime.datetime.now().timestamp()

  if is_unwatched():
    turn_display_off()
    return time.sleep(10)

  turn_display_on()

  background_requeue = []

  for background in backgrounds:
    animate_background(background)

    if is_background_invisible(background):
      backgrounds.remove(background)
      background_requeue.append(background)

  for background in background_requeue:
    background.positionX(backgrounds[-1].x() + DISPLAY.width)
    backgrounds.append(background) 

  for photo in photos:
    animate_image(photo)
          
    if is_image_invisible(photo):
      clear_image(photo)
      next_image()
    
def display():
  while DISPLAY.loop_running():
    display_images()
    
    # terminated = handle_keyboard_events()

    #if terminated:
      # break

def main():
    boot()
    display()

if __name__ == '__main__':
    main()
