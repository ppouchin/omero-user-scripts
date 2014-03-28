#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
This script tries to restore the colors for the selected LIF/LSM images.

@author Pierre Pouchin
<a href="mailto:pierre.pouchin@u-clermont1.fr">pierre.pouchin@u-clermont1.fr</a>
@version 4.3
"""

import omero
import omero.scripts as scripts
from omero.gateway import BlitzGateway
from omero.rtypes import *

PARAM_DATATYPE = "Data_Type"
PARAM_IDS = "IDs"
PARAM_COLORS = "Colors"
PARAM_ALL_IMAGES = "All_Images"

name2rgb = dict()
name2rgb['Red'] = (255,0,0)
name2rgb['Green'] = (0,255,0)
name2rgb['Blue'] = (0,0,255)
name2rgb['Yellow'] = (255,255,0)
name2rgb['Magenta'] = (255,0,255)
name2rgb['Cyan'] = (0,255,255)
name2rgb['Gray'] = (128,128,128)
name2rgb['White'] = (255,255,255)
COLOR_PLACEHOLDER = 'Auto'

colorOptions = omero.rtypes.wrap([COLOR_PLACEHOLDER] + name2rgb.keys())

################################################################################

def colorname2rgb(name) :
    """
    Gives the RGB code corresponding to a color name.
    
    @param name: The color name
    """

    if name in name2rgb:
      return name2rgb[name]
    else:
      return (255,255,255)


def getChannels(conn, image) :
    """
    Use this instead of image.getChannels() when we don't need to
    init the RenderingEngine to avoid OOM with large image counts
    """
    pid = image.getPixelsId()
    params = omero.sys.Parameters()
    params.map = {"pid": rlong(pid)}
    query = "select p from Pixels p join fetch p.channels as c join fetch c.logicalChannel as lc where p.id=:pid"
    pixels = conn.getQueryService().findByQuery(query, params, conn.SERVICE_OPTS)
    return list(pixels.iterateChannels())


def colorcode2rgb(integer) :
    """
    Gives the RGB value corresponding to an int color value.
    
    @param integer: The integer value of the color
    """

    #Integer corresponds to BGR in LSM files
    b = (integer & 16711680) >> 16
    g = (integer & 65280) >> 8
    r = (integer & 255)

    return (r,g,b)


def restore_image(conn, img, params) :
    """
    Restores the colors of one image

    @param conn:   The BlitzGateway connection
    @param img:    The ImageWrapper object
    @param params: The script parameters
    """

    treated = 0
    om = None
    cNames = dict()
    cCodes = dict()

    for idx, cName in enumerate(params[PARAM_COLORS]):
      if cName != COLOR_PLACEHOLDER:
        cNames[idx] = cName

    if len(cNames.keys()) == 0:
      om = img.loadOriginalMetadata()

    if om is not None:
      #global_metadata : om[1]
      #series_metadata : om[2]
      for keyValue in om[2]:
        if len(keyValue) > 1:
          # LIF colors
          if keyValue[0].startswith("ChannelDescription|LUTName"):
            tmp_ar = keyValue[0].split(' ')
            cNames[int(tmp_ar[1])] = keyValue[1]
          # LSM colors - try to handle both of these:
          # In OMERO 4.4 we have DataChannel #1 Color : 65280
          # In OMERO 5. we have DataChannel Color #2 : 16711680
          if keyValue[0].startswith("DataChannel") and "Color" in keyValue[0]:
            ch_idx = keyValue[0].split("#")[1].split(" ")[0]
            cCodes[int(ch_idx)-1] = int(keyValue[1])

    if cNames:
      for index, c in enumerate(getChannels(conn, img)):
        if index in cNames:
          r, g, b = colorname2rgb(cNames[index])
          cObj = conn.getQueryService().get("Channel", c.id.val)
          cObj.red = omero.rtypes.rint(r)
          cObj.green = omero.rtypes.rint(g)
          cObj.blue = omero.rtypes.rint(b)
          cObj.alpha = omero.rtypes.rint(255)
          conn.getUpdateService().saveObject(cObj)

      treated = 1
    elif cCodes:
      for index, c in enumerate(getChannels(conn, img)):
        if index in cCodes:
          r, g, b = colorcode2rgb(cCodes[index])
          cObj = conn.getQueryService().get("Channel", c.id.val)
          cObj.red = omero.rtypes.rint(r)
          cObj.green = omero.rtypes.rint(g)
          cObj.blue = omero.rtypes.rint(b)
          cObj.alpha = omero.rtypes.rint(255)
          conn.getUpdateService().saveObject(cObj)

      treated = 1


    return treated

    
def run(conn, params):
    """
    Treats each image specified.
    
    @param conn:   The BlitzGateway connection
    @param params: The script parameters
    """
    print "Parameters = %s" % params

    images = []
    if params[PARAM_ALL_IMAGES]:
      images = list(conn.getObjects('Image'))
    else:
      objects = conn.getObjects(params[PARAM_DATATYPE], params[PARAM_IDS])
      if params[PARAM_DATATYPE] == 'Dataset':
        for ds in objects:
          images.extend( list(ds.listChildren()) )
      elif params[PARAM_DATATYPE] == 'Plate':
        imageIds = []
        for p in objects:
          for well in p._listChildren():
              for ws in well.copyWellSamples():
                  imageIds.append(ws.image.id.val)
        images = conn.getObjects("Image", imageIds)
      else:
        images = list(objects)
      
      # Remove duplicate images in multiple datasets
      seen = set()
      images = [x for x in images if x.id not in seen and not seen.add(x.id)]

    # Remove images which are not writable for the user
    images = [x for x in images if x.canWrite()]
    
    print("Processing %s image%s" % (len(images), len(images) != 1 and 's' or ''))
    
    count = 0 
    resetImgIds = []
    for img in images:
      treated = restore_image(conn, img, params)
      if(treated == 1):
        resetImgIds.append(img.getId())
        count += 1

    # reset rDefs all at once
    rs = conn.getRenderingSettingsService()
    rs.resetDefaultsInSet("Image", resetImgIds)
    
    return count


def summary(count):
    """Produces a summary message (number of image(s) processed)"""
    msg = "%d image%s processed" % (count, count != 1 and 's' or '')
    return msg


def runAsScript():
    """
    The main entry point of the script, as called by the client via the 
    scripting service, passing the required parameters. 
    """
    dataTypes = [rstring('Dataset'),rstring('Image'),rstring('Plate')]
    
    client = scripts.client('Restore_colors.py', """\
    Sets channel colors for chosen images.
    Can use original metadata for LIF and LSM files or
    you can choose the channel colors manually.
    """, 
    
    scripts.String(PARAM_DATATYPE, optional=False, grouping="1",
        description="The data you want to work with.", values=dataTypes, 
        default="Image"),

    scripts.List(PARAM_IDS, optional=True, grouping="1.2",
        description="List of Dataset IDs or Image IDs").ofType(rlong(0)),

    scripts.Bool(PARAM_ALL_IMAGES, grouping="1.3", 
        description="Process all images (ignore the ID parameters)", 
        default=False),

    scripts.List(PARAM_COLORS, optional=True, grouping="2.0",
        description="Manually choose colors instead of using original metadata",
        default=COLOR_PLACEHOLDER,
        values=colorOptions).ofType(rstring("")),

    version = "1.0",
    authors = ["Pierre Pouchin", "GReD"],
    institutions = ["Universite d'Auvergne"],
    contact = "pierre.pouchin@u-clermont1.fr",
    ) 
    
    conn = BlitzGateway(client_obj=client)
    
    # Process the list of args above. 
    params = {}
    for key in client.getInputKeys():
      if client.getInput(key):
        params[key] = client.getInput(key, unwrap=True)
    
    # Call the main script - returns the number of images and total bytes
    count = run(conn, params)
    
    if count >= 0:
      # Combine the totals for the summary message
      msg = summary(count)
      print msg
      client.setOutput("Message", rstring(msg))

    client.closeSession()


if __name__ == "__main__":
    """
    Python entry point
    """
    runAsScript()
    
