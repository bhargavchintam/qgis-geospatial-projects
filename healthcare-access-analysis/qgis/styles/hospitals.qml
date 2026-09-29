<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="Symbology">
  <!-- Hospital points (results/demo/data/hospitals.gpkg): red cross marker with a white halo -->
  <renderer-v2 type="singleSymbol" forceraster="0" enableorderby="0" symbollevels="0">
    <symbols>
      <symbol type="marker" name="0" alpha="1" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleMarker" enabled="1" locked="0" pass="1">
          <Option type="Map">
            <Option type="QString" name="angle" value="0"/>
            <Option type="QString" name="color" value="255,255,255,255"/>
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="outline_color" value="80,80,80,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="scale_method" value="diameter"/>
            <Option type="QString" name="size" value="6"/>
            <Option type="QString" name="size_unit" value="MM"/>
          </Option>
        </layer>
        <layer class="SimpleMarker" enabled="1" locked="0" pass="2">
          <Option type="Map">
            <Option type="QString" name="angle" value="0"/>
            <Option type="QString" name="color" value="193,18,31,255"/>
            <Option type="QString" name="name" value="cross_fill"/>
            <Option type="QString" name="outline_color" value="193,18,31,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.2"/>
            <Option type="QString" name="scale_method" value="diameter"/>
            <Option type="QString" name="size" value="4"/>
            <Option type="QString" name="size_unit" value="MM"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <layerGeometryType>0</layerGeometryType>
</qgis>
