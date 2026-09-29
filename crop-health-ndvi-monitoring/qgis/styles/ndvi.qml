<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0" minScale="1e+08" maxScale="0">
  <pipe>
    <provider>
      <resampling enabled="false" maxOversampling="2" zoomedInResamplingMethod="nearestNeighbour" zoomedOutResamplingMethod="nearestNeighbour"/>
    </provider>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="-0.2" classificationMax="0.9" nodataColor="">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits><extent>WholeRaster</extent><statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower><cumulativeCutUpper>0.98</cumulativeCutUpper><stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <colorrampshader colorRampType="INTERPOLATED" classificationMode="1" clip="0" minimumValue="-0.2" maximumValue="0.9" labelPrecision="2">
          <colorramp type="gradient" name="[source]">
            <Option type="Map">
              <Option type="QString" name="color1" value="165,0,38,255"/>
              <Option type="QString" name="color2" value="0,104,55,255"/>
              <Option type="QString" name="stops" value="0.25;244,109,67,255:0.5;255,255,191,255:0.75;102,189,99,255"/>
            </Option>
          </colorramp>
          <item value="-0.2" label="-0.20 water / shadow" color="#a50026" alpha="255"/>
          <item value="0.075" label="0.08 bare soil" color="#f46d43" alpha="255"/>
          <item value="0.35" label="0.35 sparse crop" color="#ffffbf" alpha="255"/>
          <item value="0.625" label="0.63 dense crop" color="#66bd63" alpha="255"/>
          <item value="0.9" label="0.90 peak canopy" color="#006837" alpha="255"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" grayscaleMode="0" colorizeOn="0" colorizeRed="255" colorizeGreen="128" colorizeBlue="128" colorizeStrength="100"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
