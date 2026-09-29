<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0" minScale="1e+08" maxScale="0">
  <pipe>
    <provider>
      <resampling enabled="false" maxOversampling="2" zoomedInResamplingMethod="nearestNeighbour" zoomedOutResamplingMethod="nearestNeighbour"/>
    </provider>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="0.85" alphaBand="-1" classificationMin="0" classificationMax="1" nodataColor="">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits><extent>WholeRaster</extent><statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower><cumulativeCutUpper>0.98</cumulativeCutUpper><stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <colorrampshader colorRampType="INTERPOLATED" classificationMode="1" clip="0" minimumValue="0" maximumValue="1" labelPrecision="2">
          <colorramp type="gradient" name="[source]">
            <Option type="Map">
              <Option type="QString" name="color1" value="44,123,182,255"/>
              <Option type="QString" name="color2" value="215,25,28,255"/>
              <Option type="QString" name="stops" value="0.25;171,217,233,255:0.5;255,255,191,255:0.75;253,174,97,255"/>
            </Option>
          </colorramp>
          <item value="0" label="0.00 Very low risk" color="#2c7bb6" alpha="255"/>
          <item value="0.2" label="0.20 Low" color="#abd9e9" alpha="255"/>
          <item value="0.4" label="0.40 Moderate" color="#ffffbf" alpha="255"/>
          <item value="0.6" label="0.60 High" color="#fdae61" alpha="255"/>
          <item value="0.8" label="0.80 Very high" color="#d7191c" alpha="255"/>
          <item value="1" label="1.00 Risk index" color="#a50026" alpha="255"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" grayscaleMode="0" colorizeOn="0" colorizeRed="255" colorizeGreen="128" colorizeBlue="128" colorizeStrength="100"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
