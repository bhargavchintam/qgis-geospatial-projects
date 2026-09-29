<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="Symbology">
  <!-- Drive-time isochrone bands (results/demo/isochrones.gpkg), categorized on max_minutes, YlOrRd -->
  <renderer-v2 type="categorizedSymbol" attr="max_minutes" forceraster="0" enableorderby="0" symbollevels="0">
    <categories>
      <category value="5" label="0 to 5 min" symbol="0" render="true"/>
      <category value="10" label="5 to 10 min" symbol="1" render="true"/>
      <category value="15" label="10 to 15 min" symbol="2" render="true"/>
      <category value="20" label="15 to 20 min" symbol="3" render="true"/>
      <category value="30" label="20 to 30 min" symbol="4" render="true"/>
    </categories>
    <symbols>
      <symbol type="fill" name="0" alpha="0.7" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="255,255,178,255"/>
            <Option type="QString" name="outline_color" value="120,120,120,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.15"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="1" alpha="0.7" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="254,204,92,255"/>
            <Option type="QString" name="outline_color" value="120,120,120,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.15"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="2" alpha="0.7" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="253,141,60,255"/>
            <Option type="QString" name="outline_color" value="120,120,120,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.15"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="3" alpha="0.7" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="240,59,32,255"/>
            <Option type="QString" name="outline_color" value="120,120,120,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.15"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="4" alpha="0.7" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="189,0,38,255"/>
            <Option type="QString" name="outline_color" value="120,120,120,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.15"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <layerGeometryType>2</layerGeometryType>
</qgis>
