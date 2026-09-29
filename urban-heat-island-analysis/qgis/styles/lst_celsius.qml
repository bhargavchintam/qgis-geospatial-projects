<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0" minScale="1e+08" maxScale="0">
  <pipe>
    <provider>
      <resampling enabled="false" maxOversampling="2" zoomedInResamplingMethod="nearestNeighbour" zoomedOutResamplingMethod="nearestNeighbour"/>
    </provider>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="20" classificationMax="60" nodataColor="">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits><extent>WholeRaster</extent><statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower><cumulativeCutUpper>0.98</cumulativeCutUpper><stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <colorrampshader colorRampType="INTERPOLATED" classificationMode="1" clip="0" minimumValue="20" maximumValue="60" labelPrecision="1">
          <colorramp type="gradient" name="[source]">
            <Option type="Map">
              <Option type="QString" name="color1" value="49,54,149,255"/>
              <Option type="QString" name="color2" value="165,0,38,255"/>
              <Option type="QString" name="stops" value="0.125;69,117,180,255:0.25;116,173,209,255:0.375;171,217,233,255:0.5;255,255,191,255:0.625;253,174,97,255:0.75;244,109,67,255:0.875;215,48,39,255"/>
            </Option>
          </colorramp>
          <item value="20" label="20 °C" color="#313695" alpha="255"/>
          <item value="25" label="25 °C" color="#4575b4" alpha="255"/>
          <item value="30" label="30 °C" color="#74add1" alpha="255"/>
          <item value="35" label="35 °C" color="#abd9e9" alpha="255"/>
          <item value="40" label="40 °C" color="#ffffbf" alpha="255"/>
          <item value="45" label="45 °C" color="#fdae61" alpha="255"/>
          <item value="50" label="50 °C" color="#f46d43" alpha="255"/>
          <item value="55" label="55 °C" color="#d73027" alpha="255"/>
          <item value="60" label="60 °C" color="#a50026" alpha="255"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" grayscaleMode="0" colorizeOn="0" colorizeRed="255" colorizeGreen="128" colorizeBlue="128" colorizeStrength="100"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
