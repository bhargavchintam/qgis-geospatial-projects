<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0" minScale="1e+08" maxScale="0">
  <!-- dNBR = NBR(T1) - NBR(T2), pseudocolor -0.5 .. 0.8 with USGS burn-severity style breaks. nodata = -9999. -->
  <pipe>
    <provider>
      <resampling enabled="false" maxOversampling="2" zoomedInResamplingMethod="nearestNeighbour" zoomedOutResamplingMethod="nearestNeighbour"/>
    </provider>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="-0.5" classificationMax="0.8" nodataColor="">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits><extent>WholeRaster</extent><statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower><cumulativeCutUpper>0.98</cumulativeCutUpper><stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <colorrampshader colorRampType="INTERPOLATED" classificationMode="1" clip="0" minimumValue="-0.5" maximumValue="0.8" labelPrecision="2">
          <colorramp type="gradient" name="[source]">
            <Option type="Map">
              <Option type="QString" name="color1" value="0,104,55,255"/>
              <Option type="QString" name="color2" value="165,0,38,255"/>
              <Option type="QString" name="stops" value="0.31;166,217,106,255:0.46;255,255,191,255:0.59;253,174,97,255:0.72;244,109,67,255:0.89;215,48,39,255"/>
            </Option>
          </colorramp>
          <item value="-0.5" label="-0.50 high regrowth" color="#006837" alpha="255"/>
          <item value="-0.1" label="-0.10 low regrowth" color="#a6d96a" alpha="255"/>
          <item value="0.1" label="0.10 unchanged" color="#ffffbf" alpha="255"/>
          <item value="0.27" label="0.27 low / loss threshold" color="#fdae61" alpha="255"/>
          <item value="0.44" label="0.44 moderate-low" color="#f46d43" alpha="255"/>
          <item value="0.66" label="0.66 moderate-high" color="#d73027" alpha="255"/>
          <item value="0.8" label="0.80 high severity" color="#a50026" alpha="255"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" grayscaleMode="0" colorizeOn="0" colorizeRed="255" colorizeGreen="128" colorizeBlue="128" colorizeStrength="100"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
