<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0" minScale="1e+08" maxScale="0">
  <!-- Constraint mask (results/demo/constraints_mask.tif): 0 = excluded (grey), 1 = allowed (transparent). -->
  <pipe>
    <provider>
      <resampling enabled="false" maxOversampling="2" zoomedInResamplingMethod="nearestNeighbour" zoomedOutResamplingMethod="nearestNeighbour"/>
    </provider>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="0.8" alphaBand="-1" classificationMin="0" classificationMax="1" nodataColor="">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits><extent>WholeRaster</extent><statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower><cumulativeCutUpper>0.98</cumulativeCutUpper><stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <colorrampshader colorRampType="EXACT" classificationMode="1" clip="0" minimumValue="0" maximumValue="1" labelPrecision="0">
          <colorramp type="gradient" name="[source]">
            <Option type="Map">
              <Option type="QString" name="color1" value="128,128,128,255"/>
              <Option type="QString" name="color2" value="255,255,255,0"/>
              <Option type="QString" name="stops" value=""/>
            </Option>
          </colorramp>
          <item value="0" label="0 Excluded" color="#808080" alpha="255"/>
          <item value="1" label="1 Allowed" color="#ffffff" alpha="0"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" grayscaleMode="0" colorizeOn="0" colorizeRed="255" colorizeGreen="128" colorizeBlue="128" colorizeStrength="100"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
