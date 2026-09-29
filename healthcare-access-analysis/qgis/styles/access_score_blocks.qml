<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="Symbology">
  <!-- Block 2SFCA access score (results/demo/blocks_access.gpkg), graduated fill, 5 quantile classes
       from the demo run (beds per 1,000 residents), viridis colours -->
  <renderer-v2 type="graduatedSymbol" attr="access_score" graduatedMethod="GraduatedColor" forceraster="0" enableorderby="0" symbollevels="0">
    <ranges>
      <range lower="0.000" upper="0.304" symbol="0" label="0.00 to 0.30 (lowest 20 %)" render="true"/>
      <range lower="0.304" upper="2.292" symbol="1" label="0.30 to 2.29" render="true"/>
      <range lower="2.292" upper="4.311" symbol="2" label="2.29 to 4.31" render="true"/>
      <range lower="4.311" upper="6.443" symbol="3" label="4.31 to 6.44" render="true"/>
      <range lower="6.443" upper="9.000" symbol="4" label="6.44 to 9.00 (highest 20 %)" render="true"/>
    </ranges>
    <symbols>
      <symbol type="fill" name="0" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="68,1,84,255"/>
            <Option type="QString" name="outline_color" value="255,255,255,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.1"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="1" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="59,82,139,255"/>
            <Option type="QString" name="outline_color" value="255,255,255,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.1"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="2" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="33,145,140,255"/>
            <Option type="QString" name="outline_color" value="255,255,255,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.1"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="3" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="94,201,98,255"/>
            <Option type="QString" name="outline_color" value="255,255,255,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.1"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="4" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="253,231,37,255"/>
            <Option type="QString" name="outline_color" value="255,255,255,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.1"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
    <colorramp type="gradient" name="[source]">
      <Option type="Map">
        <Option type="QString" name="color1" value="68,1,84,255"/>
        <Option type="QString" name="color2" value="253,231,37,255"/>
        <Option type="QString" name="stops" value="0.25;59,82,139,255:0.5;33,145,140,255:0.75;94,201,98,255"/>
      </Option>
    </colorramp>
    <classificationMethod id="Quantile">
      <symmetricMode enabled="0" symmetrypoint="0" astride="0"/>
      <labelFormat format="%1 to %2" labelprecision="2" trimtrailingzeroes="0"/>
      <parameters>
        <Option/>
      </parameters>
      <extraInformation/>
    </classificationMethod>
    <mode name="quantile"/>
  </renderer-v2>
  <layerGeometryType>2</layerGeometryType>
</qgis>
