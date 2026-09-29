<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="Symbology">
  <!-- Road lines (results/demo/data/roads.gpkg) categorized on the highway class -->
  <renderer-v2 type="categorizedSymbol" attr="highway" forceraster="0" enableorderby="0" symbollevels="1">
    <categories>
      <category value="residential" label="Residential (30 km/h)" symbol="0" render="true"/>
      <category value="secondary" label="Secondary (50 km/h)" symbol="1" render="true"/>
      <category value="primary" label="Primary arterial (65 km/h)" symbol="2" render="true"/>
      <category value="motorway" label="Motorway (100 km/h)" symbol="3" render="true"/>
    </categories>
    <symbols>
      <symbol type="line" name="0" alpha="1" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="184,184,184,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="0.25"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="line" name="1" alpha="1" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="1">
          <Option type="Map">
            <Option type="QString" name="line_color" value="244,162,97,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="0.5"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="line" name="2" alpha="1" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="2">
          <Option type="Map">
            <Option type="QString" name="line_color" value="214,40,40,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="0.8"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="line" name="3" alpha="1" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="3">
          <Option type="Map">
            <Option type="QString" name="line_color" value="90,24,154,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="1.1"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <layerGeometryType>1</layerGeometryType>
</qgis>
