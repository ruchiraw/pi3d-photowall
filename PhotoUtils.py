#!/usr/bin/python
from __future__ import absolute_import, division, print_function, unicode_literals
''' Simplified slideshow system using ImageSprite and without threading for background
loading of images (so may show delay for v large images).
    Also has a minimal use of PointText and TextBlock system with reduced  codepoints
and reduced grid_size to give better resolution for large characters.
    Also shows a simple use of MQTT to control the slideshow parameters remotely
see http://pi3d.github.io/html/FAQ.html and https://www.thedigitalpictureframe.com/control-your-digital-picture-frame-with-home-assistents-wifi-presence-detection-and-mqtt/
and https://www.cloudmqtt.com/plans.html

USING exif info to rotate images

    ESC to quit, 's' to reverse, any other key to move on one.
'''
import os
import time
import random
import math
import pi3d
import locale
import subprocess
import numpy as np
from PIL import Image, ImageOps, ImageDraw

import mat_image

from pi3d.Texture import MAX_SIZE
from PIL import Image, ExifTags, ImageFilter # these are needed for getting exif data from images
import Config as config

class Pic:
  def __init__(self, fname, orientation=1, mtime=None, dt=None, fdt=None, location="", aspect=1.5):
    self.fname = fname
    self.orientation = orientation
    self.mtime = mtime
    self.dt = dt
    self.fdt = fdt
    self.location = location
    self.aspect = aspect
    self.shown_with = None # set to pic_num of image this was paired with

try:
  locale.setlocale(locale.LC_TIME, config.LOCALE)
except:
  print("error trying to set local to {}".format(config.LOCALE))

AUTO_ORIENT = False
EXIF_DATID = None # this needs to be set before get_files() above can extract exif date info
EXIF_ORIENTATION = None
#####################################################
# these variables can be altered using MQTT messaging
#####################################################
time_delay = config.TIME_DELAY
fade_time = config.FADE_TIME
shuffle = config.SHUFFLE
subdirectory = config.SUBDIRECTORY
date_from = None
date_to = None
quit = False
paused = False # NB must be set to True *only* after the first iteration of the show!
#####################################################
# only alter below here if you're keen to experiment!
#####################################################
if config.KENBURNS:
  kb_up = True
  config.FIT = False
  config.BLUR_EDGES = False
if config.BLUR_ZOOM < 1.0:
  config.BLUR_ZOOM = 1.0
delta_alpha = 1.0 / (config.FPS * fade_time) # delta alpha
last_file_change = 0.0 # holds last change time in directory structure
next_check_tm = time.time() + config.CHECK_DIR_TM # check if new file or directory every n seconds
#####################################################
# some functions to tidy subsequent code
#####################################################

# Concatenate the specified images horizontally. Clip the taller
# image to the height of the shorter image.
def create_image_pair(im1, im2):
    sep = 8 # separation between the images
    # scale widest image to same width as narrower to avoid drastic cropping on mismatched images
    if im1.width > im2.width:
      im1 = im1.resize((im2.width, int(im1.height * im2.width / im1.width)))
    else:
      im2 = im2.resize((im1.width, int(im2.height * im1.width / im2.width)))
    dst = Image.new('RGB', (im1.width + im2.width + sep, min(im1.height, im2.height)))
    dst.paste(im1, (0, 0))
    dst.paste(im2, (im1.width + sep, 0))
    return dst

def orientate_image(im, orientation):
    if orientation == 2:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    elif orientation == 3:
        im = im.transpose(Image.ROTATE_180) # rotations are clockwise
    elif orientation == 4:
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
    elif orientation == 5:
        im = im.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_270)
    elif orientation == 6:
        im = im.transpose(Image.ROTATE_270)
    elif orientation == 7:
        im = im.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_90)
    elif orientation == 8:
        im = im.transpose(Image.ROTATE_90)
    return im

def background_texture(display):
  mat_texture = Image.open('./mat_texture.jpg').convert("L")
  mat_img = mat_texture.copy()
  mat_img = mat_img.resize((display.width, display.height), resample=Image.BICUBIC)
  mat_img = ImageOps.colorize(mat_img, black='black', white='white')
  return mat_img

# --- Sanitize the specified string by removing any chars not found in config.CODEPOINTS
def sanitize_string(string):
    return ''.join([c for c in string if c in config.CODEPOINTS])

def check_changes():
  global last_file_change
  update = False
  for root, _, _ in os.walk(config.PIC_DIR):
      mod_tm = os.stat(root).st_mtime
      if mod_tm > last_file_change:
        last_file_change = mod_tm
        update = True
  return update

def get_files(dt_from=None, dt_to=None):
  # dt_from and dt_to are either None or tuples (2016,12,25)
  if dt_from is not None:
    dt_from = time.mktime(dt_from + (0, 0, 0, 0, 0, 0))
  if dt_to is not None:
    dt_to = time.mktime(dt_to + (0, 0, 0, 0, 0, 0))
  global shuffle, EXIF_DATID, last_file_change
  file_list = []
  extensions = ['.png','.jpg','.jpeg','.heif','.heic'] # can add to these
  picture_dir = os.path.join(config.PIC_DIR, subdirectory)
  for root, _dirnames, filenames in os.walk(picture_dir):
      mod_tm = os.stat(root).st_mtime # time of alteration in a directory
      if mod_tm > last_file_change:
        last_file_change = mod_tm
      for filename in filenames:
          ext = os.path.splitext(filename)[1].lower()
          if ext in extensions and not '.AppleDouble' in root and not filename.startswith('.'):
              file_path_name = os.path.join(root, filename)
              include_flag = True
              orientation = 1 # this is default - unrotated
              dt = None # if exif data not read - used for checking in tex_load
              fdt = None
              location = ""
              aspect = 1.5 # assume landscape aspect until we determine otherwise
              if not config.DELAY_EXIF and EXIF_DATID is not None and EXIF_ORIENTATION is not None:
                (orientation, dt, fdt, location, aspect) = get_exif_info(file_path_name)
                if (dt_from is not None and dt < dt_from) or (dt_to is not None and dt > dt_to):
                  include_flag = False
              if include_flag:
                # iFiles now list of lists [file_name, orientation, file_changed_date, exif_date, exif_formatted_date, aspect]
                file_list.append(Pic(file_path_name,
                                    orientation,
                                    os.path.getmtime(file_path_name),
                                    dt,
                                    fdt,
                                    location,
                                    aspect))
  if shuffle:
    file_list.sort(key=lambda x: x.mtime) # will be later files last
    temp_list_first = file_list[-config.RECENT_N:]
    temp_list_last = file_list[:-config.RECENT_N]
    random.seed()
    random.shuffle(temp_list_first)
    random.shuffle(temp_list_last)
    file_list = temp_list_first + temp_list_last
  else:
    file_list.sort() # if not suffled; sort by name
  return file_list, len(file_list) # tuple of file list, number of pictures

def get_exif_info(file_path_name, im=None):
  dt = os.path.getmtime(file_path_name) # so use file last modified date
  orientation = 1
  location = ""
  aspect = 1.5 # assume landscape aspect until we determine otherwise
  try:
    if im is None:
      im = Image.open(file_path_name) # lazy operation so shouldn't load (better test though)
    aspect = im.width / im.height
    exif_data = im._getexif() # TODO check if/when this becomes proper function
    if EXIF_DATID in exif_data:
        exif_dt = time.strptime(exif_data[EXIF_DATID], '%Y:%m:%d %H:%M:%S')
        dt = time.mktime(exif_dt)
    if EXIF_ORIENTATION in exif_data:
        orientation = int(exif_data[EXIF_ORIENTATION])
        if orientation == 6 or orientation == 8:
            aspect = 1.0 / aspect # image rotated 270 or 90 degrees
    if config.LOAD_GEOLOC and geo.EXIF_GPSINFO in exif_data:
      location = geo.get_location(exif_data[geo.EXIF_GPSINFO])
  except Exception as e: # NB should really check error here but it's almost certainly due to lack of exif data
    if config.VERBOSE:
      print('trying to read exif', e)
  fdt = time.strftime(config.SHOW_TEXT_FM, time.localtime(dt))
  return (orientation, dt, fdt, location, aspect)

def convert_heif(fname):
    try:
        import pyheif
        from PIL import Image

        heif_file = pyheif.read(fname)
        image = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data,
                                "raw", heif_file.mode, heif_file.stride)
        return image
    except:
        print("have you installed pyheif?")

def get_matter(display):
  matter = mat_image.MatImage(
    display_size = (display.width , display.height),
    outer_mat_border = 0
  )
  return matter

def tex_load(matter, pic_num, iFiles, size=None):
  global date_from, date_to, next_pic_num
  if type(pic_num) is int:
    #fname = iFiles[pic_num][0]
    #orientation = iFiles[pic_num][1]
    fname = iFiles[pic_num].fname
    orientation = iFiles[pic_num].orientation if AUTO_ORIENT else 1
    if iFiles[pic_num].shown_with is not None:
      return None # this image already show this round so skip
  else: # allow file name to be passed to this function ie for missing file image
    fname = pic_num
    orientation = 1
  try:
    ext = os.path.splitext(fname)[1].lower()
    if ext in ('.heif','.heic'):
      im = convert_heif(fname)
    else:
      im = Image.open(fname)
    if config.DELAY_EXIF and type(pic_num) is int: # don't do this if passed a file name
      if iFiles[pic_num].dt is None or iFiles[pic_num].fdt is None: # dt and fdt set to None before exif read
        (orientation, dt, fdt, location, aspect) = get_exif_info(fname, im)
        iFiles[pic_num].orientation = orientation
        iFiles[pic_num].dt = dt
        iFiles[pic_num].fdt = fdt
        iFiles[pic_num].location = location
        iFiles[pic_num].aspect = aspect

      if date_from is not None:
        if dt < time.mktime(date_from + (0, 0, 0, 0, 0, 0)):
          return None
      if date_to is not None:
        if dt > time.mktime(date_to + (0, 0, 0, 0, 0, 0)):
          return None

    # If PORTRAIT_PAIRS active and this is a portrait pic, try to find another one to pair it with
    if config.PORTRAIT_PAIRS and iFiles[pic_num].aspect < 1.0:
      im2 = None
      # Search the whole list for another portrait image, starting with the "next"
      # assuming previous images in sequence have already been shown
      # TODO poss very time consuming to call get_exif_info
      # TODO back and next will bring up different image combinations, or maybe just fail
      if pic_num < len(iFiles) - 1: # i.e can't do this on the last image in list
        for f_rec in iFiles[pic_num + 1:]:
          if f_rec.dt is None or f_rec.fdt is None: # dt and fdt set to None before exif read
            (f_orientation, f_dt, f_fdt, f_location, f_aspect) = get_exif_info(f_rec.fname)
            f_rec.orientation = f_orientation
            f_rec.dt = f_dt
            f_rec.fdt = f_fdt
            f_rec.location = f_location
            f_rec.aspect = f_aspect
          if f_rec.aspect < 1.0 and f_rec.shown_with is None:
            im2 = Image.open(f_rec.fname)
            f_rec.shown_with = pic_num
            break
      if im2 is not None:
        if orientation > 1:
          im = orientate_image(im, orientation)
        if f_rec.orientation > 1:
          im2 = orientate_image(im2, f_rec.orientation)
        im = create_image_pair(im, im2)
        orientation = 1

    im = matter.mat_image((im,))

    (w, h) = im.size
    max_dimension = MAX_SIZE # TODO changing MAX_SIZE causes serious crash on linux laptop!
    if not config.AUTO_RESIZE: # turned off for 4K display - will cause issues on RPi before v4
        max_dimension = 3840 # TODO check if mipmapping should be turned off with this setting.
    if w > max_dimension:
        im = im.resize((max_dimension, int(h * max_dimension / w)), resample=Image.BICUBIC)
    elif h > max_dimension:
        im = im.resize((int(w * max_dimension / h), max_dimension), resample=Image.BICUBIC)
    if orientation > 1:
        im = orientate_image(im, orientation)
    if config.BLUR_EDGES and size is not None:
      wh_rat = (size[0] * im.height) / (size[1] * im.width)
      if abs(wh_rat - 1.0) > 0.01: # make a blurred background
        (sc_b, sc_f) = (size[1] / im.height, size[0] / im.width)
        if wh_rat > 1.0:
          (sc_b, sc_f) = (sc_f, sc_b) # swap round
        (w, h) = (round(size[0] / sc_b / config.BLUR_ZOOM), round(size[1] / sc_b / config.BLUR_ZOOM))
        (x, y) = (round(0.5 * (im.width - w)), round(0.5 * (im.height - h)))
        box = (x, y, x + w, y + h)
        blr_sz = (int(x * 512 / size[0]) for x in size)
        im_b = im.resize(size, resample=0, box=box).resize(blr_sz)
        im_b = im_b.filter(ImageFilter.GaussianBlur(config.BLUR_AMOUNT))
        im_b = im_b.resize(size, resample=Image.BICUBIC)
        im_b.putalpha(round(255 * config.EDGE_ALPHA))  # to apply the same EDGE_ALPHA as the no blur method.
        im = im.resize((int(x * sc_f) for x in im.size), resample=Image.BICUBIC)
        """resize can use Image.LANCZOS (alias for Image.ANTIALIAS) for resampling
        for better rendering of high-contranst diagonal lines. NB downscaled large
        images are rescaled near the start of this try block if w or h > max_dimension
        so those lines might need changing too.
        """
        im_b.paste(im, box=(round(0.5 * (im_b.width - im.width)),
                            round(0.5 * (im_b.height - im.height))))
        im = im_b # have to do this as paste applies in place
    tex = pi3d.Texture(im, blend=True, m_repeat=True, automatic_resize=config.AUTO_RESIZE,
                        free_after_load=True)
    #tex = pi3d.Texture(im, blend=True, m_repeat=True, automatic_resize=config.AUTO_RESIZE,
    #                    mipmap=config.AUTO_RESIZE, free_after_load=True) # poss try this if still some artifacts with full resolution
  except Exception as e:
    if config.VERBOSE:
        print('''Couldn't load file {} giving error: {}'''.format(fname, e))
    tex = None
  return (tex, im)
