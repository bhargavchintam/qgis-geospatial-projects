<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0" minScale="1e+08" maxScale="0">
  <!-- Suitability classes 1..5 (results/demo/suitability_classes.tif). 0 = excluded (nodata). -->
  <pipe>
    <provider>
      <resampling enabled="false" maxOversampling="2" zoomedInResamplingMethod="nearestNeighbour" zoomedOutResamplingMethod="nearestNeighbour"/>
    </provider>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="1" classificationMax="5" nodataColor="">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits><extent>WholeRaster</extent><statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower><cumulativeCutUpper>0.98</cumulativeCutUpper><stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <colorrampshader colorRampType="EXACT" classificationMode="1" clip="0" minimumValue="1" maximumValue="5" labelPrecision="0">
          <colorramp type="gradient" name="[source]">
            <Option type="Map">
              <Option type="QString" name="color1" value="215,25,28,255"/>
              <Option type="QString" name="color2" value="26,150,65,255"/>
              <Option type="QString" name="stops" value="0.25;253,174,97,255:0.5;255,255,191,255:0.75;166,217,106,255"/>
            </Option>
          </colorramp>
          <item value="1" label="1 Very Low" color="#d7191c" alpha="255"/>
          <item value="2" label="2 Low" color="#fdae61" alpha="255"/>
          <item value="3" label="3 Moderate" color="#ffffbf" alpha="255"/>
          <item value="4" label="4 High" color="#a6d96a" alpha="255"/>
          <item value="5" label="5 Very High" color="#1a9641" alpha="255"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" grayscaleMode="0" colorizeOn="0" colorizeRed="255" colorizeGreen="128" colorizeBlue="128" colorizeStrength="100"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
